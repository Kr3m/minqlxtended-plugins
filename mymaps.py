"""
mymaps.py - map command override with optional map-pool-aware factory resolution.
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
else:
    HIGHEST = minqlx.Priority.HIGHEST
    STOP_ALL = minqlx.Return.STOP_ALL
    USAGE = minqlx.Return.USAGE


class mymaps(minqlx.Plugin):
    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_mymaps_enable", "1")
        self.set_cvar_once("qlx_mymaps_vote_enable", "1")
        self.set_cvar_once("qlx_defaultFactory", "")
        self.set_cvar_once("qlx_enforceMappool", "0")

        # Simple in-memory cache for parsed map pool, invalidated by file mtime/path changes.
        self._cached_pool_path = None
        self._cached_pool_stamp = None
        self._cached_pool_data = None
        self._reissuing_vote = False

        self.add_command(
            ("map", "changemap"),
            self.cmd_map,
            permission=2,  # matches essentials !map permission
            priority=HIGHEST,
            usage="<mapname> [factory]",
        )
        self.add_hook("vote_called", self.handle_vote_called)
        self.logger.info("mymaps diagnostics ready: vote_called hook registered.")

    def handle_vote_called(self, caller, vote, args):
        self.logger.info(
            f"vote_called ENTER: vote={vote!r} args={args!r} caller={caller.name if caller else 'server'}"
        )
        if self._reissuing_vote:
            self.logger.info("vote_called SKIP: reissued command; recursion guard active.")
            return
        if not self._vote_feature_enabled():
            self.logger.info("vote_called SKIP: qlx_mymaps_vote_enable is disabled.")
            return
        if caller is None:
            self.logger.warning("Map vote resolution requires a player caller; leaving vote unchanged.")
            return

        vote_name = vote.strip()
        parts = args.split()
        if vote_name.lower() == "map":
            if parts and parts[0].lower() == "map":
                parts = parts[1:]
        elif not parts and self._is_map_vote_shorthand(vote_name):
            parts = [vote_name]
        else:
            self.logger.info("vote_called SKIP: not a recognized map vote.")
            return
        if len(parts) not in (1, 2):
            self.logger.warning("Map vote has unexpected arguments %r; leaving it unchanged.", args)
            return
        map_name = parts[0]
        explicit_factory = parts[1] if len(parts) == 2 else None
        self.logger.info("Map vote parsed: map=%r explicit_factory=%r.", map_name, explicit_factory)

        factory, rule = self._resolve_factory_details(map_name, explicit_factory, require_pool=True)
        self.logger.info("Map vote resolved: map=%r factory=%r rule=%r.", map_name, factory, rule)
        if not factory:
            self.logger.warning("Map vote '%s': no factory resolved; rewritten=no.", map_name)
            return
        if explicit_factory:
            self.logger.info("Map vote '%s': %s factory '%s'; rewritten=no.", map_name, rule, factory)
            return
        if not all(re.fullmatch(r"[A-Za-z0-9_./-]+", value) for value in (map_name, factory)):
            self.logger.warning(
                "Map vote '%s': %s factory %r is unsafe for reissuance; rewritten=no.",
                map_name, rule, factory
            )
            return

        flags = self._read_cvar("g_voteFlags", None)
        try:
            factory_votes_disabled = bool(int(flags) & 8)
        except (ValueError, TypeError):
            self.logger.warning(
                "Map vote '%s': %s factory '%s'; cannot read g_voteFlags %r, rewritten=no.",
                map_name, rule, factory, flags
            )
            return
        if factory_votes_disabled:
            self.logger.warning(
                "Map vote '%s': %s factory '%s'; g_voteFlags bit 8 is set. "
                "Clear bit 8 to allow factory rewriting; rewritten=no.",
                map_name, rule, factory
            )
            return
        if self.is_vote_active():
            self.logger.info(
                "Map vote '%s': %s factory '%s'; another vote is active, rewritten=no.",
                map_name, rule, factory
            )
            return

        command = f"callvote map {map_name} {factory}"
        self.logger.info(
            "Vote rewrite context: g_voteFlags=%r qlx_enforceMappool=%r.",
            flags, self._read_cvar("qlx_enforceMappool")
        )
        self._reissuing_vote = True
        try:
            self.logger.info(f"REWRITING vote: map={map_name!r} factory={factory!r}")
            if self._try_vote_command(caller, command, is_rewrite=True):
                self.logger.info(
                    "Map vote '%s': %s factory '%s'; rewritten=yes.", map_name, rule, factory
                )
            else:
                self.logger.error(
                    "Map vote '%s': %s factory '%s'; rewrite rejected, rewritten=no. "
                    "Replaying original vote.", map_name, rule, factory
                )
                original = f"callvote {vote}" + (f" {args}" if args else "")
                if not self._try_vote_command(caller, original):
                    self.logger.error("Original vote replay also failed: %r.", original)
        finally:
            self._reissuing_vote = False
        self.logger.info("vote_called EXIT: returning STOP_ALL after rewrite/replay.")
        return STOP_ALL

    def _try_vote_command(self, caller, command, *, is_rewrite=False):
        delivered = None
        try:
            delivered = minqlx.client_command(caller.id, command)
            if is_rewrite:
                self.logger.info("REWRITE client_command sent")
            else:
                self.logger.info("Original vote replay client_command sent")
        except (ValueError, TypeError, RuntimeError) as exc:
            self.logger.error("Vote command %r failed: %s.", command, exc)
        else:
            if not delivered:
                self.logger.error("Vote command %r was not delivered.", command)
        active = self.is_vote_active()
        self.logger.info(
            "Vote command result: command=%r delivered=%r active=%r.", command, delivered, active
        )
        return active

    def _is_map_vote_shorthand(self, vote):
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", vote):
            return False
        pool = self._parse_map_pool()
        if pool is None:
            return False
        if vote.lower() in pool:
            return True
        map_info = getattr(minqlx, "map_info", None)
        if map_info is None:
            self.logger.debug("Cannot identify bare vote %r as a map; use /callvote map <mapname>.", vote)
            return False
        try:
            return map_info(vote) is not None
        except (OSError, ValueError, RuntimeError) as exc:
            self.logger.warning("Could not identify bare map vote %r: %s.", vote, exc)
            return False

    def cmd_map(self, player, msg, channel):
        if len(msg) < 2:
            return USAGE

        map_name = msg[1].strip()
        if not map_name:
            return USAGE

        explicit_factory = msg[2].strip() if len(msg) > 2 and msg[2].strip() else None

        # Enforce map pool restrictions on !map when qlx_enforceMappool is enabled.
        if self._enforce_mappool_enabled():
            allowed, canonical_factory = self._validate_against_mappool(
                map_name, explicit_factory, channel
            )
            if not allowed:
                return STOP_ALL
            # Use the pool's exact factory string (or default to the first pool factory).
            explicit_factory = canonical_factory

        # Toggle branch:
        # - disabled => reimplement stock !map without pool/default-factory lookup
        # - enabled  => apply enhanced map-pool-aware factory resolution
        if not self._feature_enabled():
            return self._load_map(map_name, explicit_factory, channel)

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

    def _validate_against_mappool(self, map_name, explicit_factory, channel):
        """
        Validates (map_name, explicit_factory) against the configured map pool.
        Returns (True, resolved_pool_factory) if allowed, or (False, None) if blocked.
        """
        pool = self._parse_map_pool()
        if not pool:
            self.logger.warning(
                "qlx_enforceMappool is enabled, but map pool could not be loaded; blocking !map %s.",
                map_name,
            )
            channel.reply("^1Cannot change map: qlx_enforceMappool is enabled, but the map pool is unavailable.")
            return False, None

        allowed_factories = pool.get(map_name.lower())
        if not allowed_factories:
            channel.reply(
                "^1Map '^7{}^1' is not in the map pool (qlx_enforceMappool is enabled).".format(map_name)
            )
            return False, None

        if explicit_factory:
            for factory in allowed_factories:
                if factory.lower() == explicit_factory.lower():
                    return True, factory
            channel.reply(
                "^1Factory '^7{}^1' is not allowed for '^7{}^1'. Allowed: ^7{}^1.".format(
                    explicit_factory, map_name, ", ".join(allowed_factories)
                )
            )
            return False, None

        # No factory specified: enforce the first pool factory for this map.
        return True, allowed_factories[0]

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
        return self._enabled_cvar("qlx_mymaps_enable", default="1")

    def _vote_feature_enabled(self):
        return self._enabled_cvar("qlx_mymaps_vote_enable", default="1")

    def _enforce_mappool_enabled(self):
        return self._enabled_cvar("qlx_enforceMappool", default="0")

    def _enabled_cvar(self, name, default="1"):
        raw_value = self._read_cvar(name, default)
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False

        fallback = default.strip().lower() in {"1", "true", "on", "yes"}
        self.logger.warning(
            "Invalid %s value '%s'. Expected 0/1 (or true/false/on/off). "
            "Falling back to %s.",
            name,
            raw_value,
            "enabled" if fallback else "disabled",
        )
        return fallback

    def _get_default_factory_cvar(self):
        return self._read_cvar("qlx_defaultFactory").strip()

    def _resolve_factory(self, map_name, explicit_factory):
        factory, _ = self._resolve_factory_details(map_name, explicit_factory)
        return factory

    def _resolve_factory_details(self, map_name, explicit_factory, require_pool=False):
        if explicit_factory:
            return self._resolved_factory(map_name, explicit_factory, "explicit"), "explicit"

        pool = self._parse_map_pool()
        if pool is None and require_pool:
            return None, None
        if pool:
            pool_factories = pool.get(map_name.lower())
            if pool_factories:
                return self._resolved_factory(map_name, pool_factories[0], "pool"), "pool"

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
                    factories = parsed.setdefault(key, [])
                    if not any(existing.lower() == factory.lower() for existing in factories):
                        factories.append(factory)
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
