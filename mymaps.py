"""
mymaps.py - map command override with optional map-pool-aware factory resolution.

Purpose
-------
Overrides !map <mapname> [factory] to support map-pool-aware factory selection when enabled.
For native /callvote map votes, an independent toggle enables the same selection.
The native vote starts unchanged; after it starts, its execution command is updated.
The displayed vote text remains unchanged, and native callvote validation does not
validate the added factory.
Votes that start and end between frame polls may not be updated.

Enabled behavior (!map <mapname> [factory]):
  1) If [factory] is explicitly provided, use it.
  2) If [factory] is omitted and map is listed in sv_mapPoolFile/sv_mappoolfile, use pool factory.
  3) For an unlisted map, use nonblank qlx_defaultFactory.
  4) Otherwise use the currently running factory.
  5) If no factory can be resolved, log an error and notify the caller without loading.

Disabled behavior:
  Faithfully reimplements stock !map behavior from essentials, rather than delegating
  to a potentially customized handler. No pool/default-factory lookup is performed:
    self.change_map(msg[1], msg[2] if len(msg) > 2 else None)

Install / load notes
--------------------
- This plugin registers "map"/"changemap" at PRI_HIGHEST and returns RET_STOP_ALL after handling.
  That gives it precedence over lower-priority handlers, including essentials.
- Keep essentials loaded for all other commands/features.
- If another plugin also registers !map at PRI_HIGHEST, load order between those two will matter.
  Unload that competing override (including a separate map.py), or load mymaps first.
- Supports minqlx and minqlxtended; add_command is the command-registration API,
  not console_command (which executes an engine command).
- Relative pool paths resolve under fs_homepath/baseq3, then fs_basepath/baseq3.
  Absolute pool paths are supported. Parsed pools are cached by path and stat fingerprint;
  edits are picked up on the next command, without reloading the plugin.
- !map factory IDs are passed through to QL for validation, including qlx_defaultFactory.
- Callvote resolution requires minqlxtended's writable level.vote_string and vote_started
  hook. Legacy minqlx retains !map support but does not get this callvote feature.
- g_voteFlags bit 8 may prohibit factory arguments in native map votes. This plugin
  leaves explicit arguments to QL and warns when it adds a factory under that flag;
  updating the started vote bypasses QL's factory-argument check.

Custom Cvars
------------
- qlx_mymaps_enable (default: "1")
    1/on/true/yes  -> enabled (map-pool-aware resolution)
    0/off/false/no -> disabled (stock !map behavior)
- qlx_mymaps_vote_enable (default: "1")
    1/on/true/yes  -> enable factory resolution for native map votes
    0/off/false/no -> leave map votes untouched
- qlx_defaultFactory (default: "", string)
    Factory for unlisted maps when no explicit factory is supplied. Empty/blank means
    use the currently running factory. Toggles and default are read live.
"""

import os
import re

try:
    import minqlxtended as minqlx
except ModuleNotFoundError as exc:
    if exc.name != "minqlxtended":
        raise
    import minqlx

    HIGHEST = minqlx.PRI_HIGHEST
    STOP_ALL = minqlx.RET_STOP_ALL
    USAGE = minqlx.RET_USAGE
    EXTENDED = False
else:
    HIGHEST = minqlx.Priority.HIGHEST
    STOP_ALL = minqlx.Return.STOP_ALL
    USAGE = minqlx.Return.USAGE
    EXTENDED = True


class mymaps(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_mymaps_enable", "1")
        self.set_cvar_once("qlx_mymaps_vote_enable", "1")
        self.set_cvar_once("qlx_defaultFactory", "")

        # Simple in-memory cache for parsed map pool, invalidated by file mtime/path changes.
        self._cached_pool_path = None
        self._cached_pool_stamp = None
        self._cached_pool_data = None
        self._pending_map_vote = None
        self._pending_vote_frame_seen = False

        self.add_command(
            ("map", "changemap"),
            self.cmd_map,
            permission=2,  # matches essentials !map permission
            priority=HIGHEST,
            usage="<mapname> [factory]",
        )
        if EXTENDED and hasattr(minqlx, "level"):
            self.add_hook("vote_called", self.handle_vote_called)
            self.add_hook("vote_started", self.handle_vote_started)
        else:
            self.logger.warning("Map vote resolution requires minqlxtended's level API.")

    def handle_vote_called(self, caller, vote, args):
        # Detection occurs before native validation; never cancel the original vote.
        if self._pending_map_vote and self.is_vote_active():
            return
        self._clear_pending_vote()
        if vote.lower() != "map" or not self._vote_feature_enabled():
            return

        parts = args.split()
        if len(parts) not in (1, 2):
            self.logger.warning("Map vote has unexpected arguments %r; leaving it unchanged.", args)
            return
        map_name = parts[0]
        explicit_factory = parts[1] if len(parts) == 2 else None
        # The shared resolver preserves !map's priority; votes require a readable pool.
        factory, rule = self._resolve_factory_details(map_name, explicit_factory, require_pool=True)
        if not factory:
            self.logger.warning("Map vote '%s': no factory resolved; leaving it unchanged.", map_name)
            return
        if explicit_factory:
            self.logger.info("Map vote '%s': %s factory '%s'; rewritten=no.", map_name, rule, factory)
            return
        if not all(re.fullmatch(r"[A-Za-z0-9_./-]+", value) for value in (map_name, factory)):
            self.logger.warning("Map vote '%s': unsafe map or factory; leaving it unchanged.", map_name)
            return

        flags = self._read_cvar("g_voteFlags")
        try:
            if flags and int(flags) & 8:
                self.logger.warning(
                    "Map vote '%s': g_voteFlags bit 8 may prohibit native factory arguments; "
                    "updating the started vote bypasses that check.", map_name
                )
        except ValueError:
            self.logger.warning("Invalid g_voteFlags value %r; cannot check bit 8.", flags)

        self.add_hook("frame", self._expire_pending_vote)
        self._pending_map_vote = (caller.id, map_name, factory, rule)
        self._pending_vote_frame_seen = False

    def handle_vote_started(self, caller, vote, args):
        pending = self._pending_map_vote
        if not pending:
            return
        self._clear_pending_vote()
        caller_id, map_name, factory, rule = pending
        parts = args.split()
        if (
            caller is None or caller.id != caller_id or vote.lower() != "map"
            or len(parts) not in (1, 2) or parts[0].lower() != map_name.lower()
        ):
            self.logger.warning("Map vote '%s': started vote did not match; rewritten=no.", map_name)
            return

        try:
            level = minqlx.level
            original = level.vote_string
            if original.split() != [vote, *parts] or not level.vote_time:
                self.logger.warning("Map vote '%s': execution command changed; rewritten=no.", map_name)
                return
            level.vote_string = f"map {map_name} {factory}"
        except (minqlx.EngineStateError, ValueError, TypeError, RuntimeError) as exc:
            # A failed assignment leaves the original native vote in place.
            self.logger.error("Map vote '%s': rewrite failed (%s); rewritten=no.", map_name, exc)
            return
        self.logger.info("Map vote '%s': %s factory '%s'; rewritten=yes.", map_name, rule, factory)

    def _expire_pending_vote(self):
        if self._pending_map_vote is None:
            return
        if self._pending_vote_frame_seen:
            _, map_name, factory, rule = self._pending_map_vote
            self.logger.warning(
                "Map vote '%s': %s factory '%s'; vote not observed starting, rewritten=no.",
                map_name, rule, factory
            )
            self._clear_pending_vote()
        else:
            self._pending_vote_frame_seen = True

    def _clear_pending_vote(self):
        if self._pending_map_vote is not None:
            self._pending_map_vote = None
            self.remove_hook("frame", self._expire_pending_vote)

    def cmd_map(self, player, msg, channel):
        if len(msg) < 2:
            return USAGE

        map_name = msg[1].strip()
        if not map_name:
            return USAGE

        explicit_factory = msg[2].strip() if len(msg) > 2 and msg[2].strip() else None

        # Toggle branch:
        # - disabled => reimplement stock !map without pool/default-factory lookup
        # - enabled  => apply enhanced map-pool-aware factory resolution
        if not self._feature_enabled():
            return self._default_map_behavior(player, msg, channel)

        resolved_factory = self._resolve_factory(map_name, explicit_factory)
        if resolved_factory is None:
            self.logger.error(
                "Cannot load map '%s': qlx_defaultFactory is empty and the current factory is unavailable.",
                map_name,
            )
            channel.reply(
                "^1Cannot load map '{}': no factory is available. "
                "Specify a factory explicitly or set qlx_defaultFactory.".format(map_name)
            )
            return STOP_ALL

        return self._load_map(map_name, resolved_factory, channel)

    def _load_map(self, map_name, factory, channel):
        try:
            self.change_map(map_name, factory)
        except (ValueError, RuntimeError, minqlx.NonexistentGameError):
            self.logger.exception("Failed to load map '%s' with factory '%s'.", map_name, factory)
            channel.reply("^1Failed to load map '{}'. See the server log for details.".format(map_name))

        # Prevent lower-priority !map handlers from running.
        return STOP_ALL

    def _read_cvar(self, name, default=""):
        try:
            value = self.get_cvar(name)
        except Exception as exc:
            self.logger.warning("Failed reading %s (%s). Using default %r.", name, exc, default)
            return default
        return default if value is None else value

    def _feature_enabled(self):
        return self._enabled_cvar("qlx_mymaps_enable")

    def _vote_feature_enabled(self):
        return self._enabled_cvar("qlx_mymaps_vote_enable")

    def _enabled_cvar(self, name):
        raw_value = self._read_cvar(name, "1")
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False

        self.logger.warning(
            "Invalid %s value '%s'. Expected 0/1 (or true/false/on/off). "
            "Falling back to enabled.",
            name,
            raw_value,
        )
        return True

    def _get_default_factory_cvar(self):
        return self._read_cvar("qlx_defaultFactory").strip()

    def _default_map_behavior(self, player, msg, channel):
        return self._load_map(msg[1], msg[2] if len(msg) > 2 else None, channel)

    def _resolve_factory(self, map_name, explicit_factory):
        factory, _ = self._resolve_factory_details(map_name, explicit_factory)
        return factory

    def _resolve_factory_details(self, map_name, explicit_factory, require_pool=False):
        # Factory resolution decision tree (enabled mode):
        # 1) explicit factory argument wins
        # 2) else map-pool factory for listed maps
        # 3) else nonblank qlx_defaultFactory
        # 4) else currently running factory
        # 5) else fail without issuing a map command
        if explicit_factory:
            return self._resolved_factory(map_name, explicit_factory, "explicit"), "explicit"

        pool = self._parse_map_pool()
        if pool is None and require_pool:
            return None, None
        if pool:
            pool_factory = pool.get(map_name.lower())
            if pool_factory:
                return self._resolved_factory(map_name, pool_factory, "pool"), "pool"

        default_factory = self._get_default_factory_cvar()
        if default_factory:
            return self._resolved_factory(map_name, default_factory, "qlx_defaultFactory"), "qlx_defaultFactory"

        current_factory = self._current_factory()
        if current_factory:
            return self._resolved_factory(map_name, current_factory, "current factory"), "current factory"

        return None, None

    def _resolved_factory(self, map_name, factory, rule):
        self.logger.debug("Map '%s': resolved factory '%s' using %s.", map_name, factory, rule)
        return factory

    def _current_factory(self):
        try:
            game = self.game
            if game is None:
                return None
            factory = game.factory
        except (minqlx.NonexistentGameError, KeyError) as exc:
            self.logger.warning("Could not determine the current factory: %s", exc)
            return None

        return factory.strip() if factory else None

    def _parse_map_pool(self):
        pool_path = self._resolve_map_pool_path()
        if not pool_path:
            self._clear_pool_cache()
            return None

        try:
            stat = os.stat(pool_path)
            pool_stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        except OSError as exc:
            self.logger.warning("Could not stat map pool file '%s': %s", pool_path, exc)
            self._clear_pool_cache()
            return None

        if (
            self._cached_pool_data is not None
            and self._cached_pool_path == pool_path
            and self._cached_pool_stamp == pool_stamp
        ):
            return self._cached_pool_data

        parsed = {}
        try:
            with open(pool_path, "r", encoding="utf-8") as pool_file:
                for line_number, raw_line in enumerate(pool_file, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if line.count("|") != 1:
                        self.logger.warning(
                            "Skipping malformed map pool line %d in '%s': expected one '|'.",
                            line_number,
                            pool_path,
                        )
                        continue

                    map_name, factory = [part.strip() for part in line.split("|", 1)]
                    if not map_name or not factory:
                        self.logger.warning(
                            "Skipping malformed map pool line %d in '%s': empty map or factory.",
                            line_number,
                            pool_path,
                        )
                        continue

                    key = map_name.lower()
                    if key in parsed and parsed[key] != factory:
                        self.logger.warning(
                            "Duplicate map '%s' in '%s' line %d. Keeping '%s', ignoring '%s'.",
                            map_name,
                            pool_path,
                            line_number,
                            parsed[key],
                            factory,
                        )
                        continue

                    parsed[key] = factory
        except (OSError, UnicodeError) as exc:
            self.logger.warning("Could not read map pool file '%s': %s", pool_path, exc)
            self._clear_pool_cache()
            return None

        self._cached_pool_path = pool_path
        self._cached_pool_stamp = pool_stamp
        self._cached_pool_data = parsed
        return parsed

    def _resolve_map_pool_path(self):
        map_pool_cvar = self._read_cvar("sv_mapPoolFile").strip()
        if not map_pool_cvar:
            self.logger.warning("sv_mapPoolFile/sv_mappoolfile is not set.")
            return None

        if os.path.isabs(map_pool_cvar):
            if os.path.isfile(map_pool_cvar):
                return map_pool_cvar
            self.logger.warning("Configured map pool file does not exist: '%s'.", map_pool_cvar)
            return None

        candidates = []
        fs_homepath = self._read_cvar("fs_homepath")
        fs_basepath = self._read_cvar("fs_basepath")

        if fs_homepath:
            candidates.append(os.path.join(fs_homepath, "baseq3", map_pool_cvar))
        if fs_basepath:
            candidates.append(os.path.join(fs_basepath, "baseq3", map_pool_cvar))

        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)

            if os.path.isfile(candidate):
                return candidate

        self.logger.warning(
            "Map pool file '%s' not found in fs_homepath/fs_basepath candidate locations.",
            map_pool_cvar,
        )
        return None

    def _clear_pool_cache(self):
        self._cached_pool_path = None
        self._cached_pool_stamp = None
        self._cached_pool_data = None