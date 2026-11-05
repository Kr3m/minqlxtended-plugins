"""
mymaps.py - map command override with optional map-pool-aware factory resolution.

Purpose
-------
Overrides !map <mapname> [factory] to support map-pool-aware factory selection when enabled.

Enabled behavior (!map <mapname> [factory]):
  1) If [factory] is explicitly provided, use it.
  2) If [factory] is omitted and map is listed in sv_mapPoolFile/sv_mappoolfile, use pool factory.
  3) If [factory] is omitted and map is not listed in pool, use currently loaded factory.
  4) If no factory can be resolved, change map without factory (engine/default behavior).

Disabled behavior:
  Reverts to stock !map behavior from essentials:
    self.change_map(msg[1], msg[2] if len(msg) > 2 else None)

Install / load notes
--------------------
- This plugin registers "map"/"changemap" at PRI_HIGHEST and returns RET_STOP_ALL after handling.
  That gives it precedence over lower-priority handlers, including essentials.
- Keep essentials loaded for all other commands/features.
- If another plugin also registers !map at PRI_HIGHEST, load order between those two will matter.

Custom Cvars
------------
- qlx_mymaps_enable (default: "1")
    1/on/true/yes  -> enabled (map-pool-aware resolution)
    0/off/false/no -> disabled (stock !map behavior)
"""

import os

import minqlxtended


class mymaps(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()

        # Primary feature toggle (default enabled).
        self.set_cvar_once("qlx_mymaps_enable", "1")

        # Simple in-memory cache for parsed map pool, invalidated by file mtime/path changes.
        self._cached_pool_path = None
        self._cached_pool_mtime = None
        self._cached_pool_data = None

        self.add_command(
            ("map", "changemap"),
            self.cmd_map,
            permission=2,  # matches essentials !map permission
            priority=minqlxtended.Priority.HIGHEST,
            usage="<mapname> [factory]",
        )

    def cmd_map(self, player, msg, channel):
        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        map_name = msg[1].strip()
        if not map_name:
            return minqlxtended.Return.USAGE

        explicit_factory = msg[2].strip() if len(msg) > 2 and msg[2].strip() else None

        # Toggle branch:
        # - disabled => revert to stock !map behavior (delegate to essentials if present)
        # - enabled  => apply enhanced map-pool-aware factory resolution
        if not self._feature_enabled():
            return self._default_map_behavior(player, msg, channel, map_name, explicit_factory)

        resolved_factory = self._resolve_factory(map_name, explicit_factory)
        self.change_map(map_name, resolved_factory)

        # Prevent lower-priority !map handlers from running.
        return minqlxtended.Return.STOP_ALL

    def _feature_enabled(self):
        try:
            raw_value = self.get_cvar("qlx_mymaps_enable")
        except Exception as exc:
            self.logger.warning(
                "Failed reading qlx_mymaps_enable (%s). Falling back to default enabled state.",
                exc,
            )
            return True

        if raw_value is None:
            return True  # default if unset/missing

        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "on", "yes"}:
            return True
        if normalized in {"0", "false", "off", "no"}:
            return False

        self.logger.warning(
            "Invalid qlx_mymaps_enable value '%s'. Expected 0/1 (or true/false/on/off). "
            "Falling back to enabled.",
            raw_value,
        )
        return True

    def _default_map_behavior(self, player, msg, channel, map_name, explicit_factory):
        # Delegate to stock essentials handler when available to preserve exact behavior.
        essentials_plugin = self.plugins.get("essentials")
        if essentials_plugin and hasattr(essentials_plugin, "cmd_map"):
            result = essentials_plugin.cmd_map(player, msg, channel)
            if result == minqlxtended.Return.USAGE:
                return minqlxtended.Return.USAGE
            return minqlxtended.Return.STOP_ALL

        # Fallback: faithful reimplementation of stock essentials cmd_map semantics.
        self.change_map(map_name, explicit_factory)
        return minqlxtended.Return.STOP_ALL

    def _resolve_factory(self, map_name, explicit_factory):
        # Factory resolution decision tree (enabled mode):
        # 1) explicit factory argument wins
        # 2) else map-pool factory for listed maps
        # 3) else currently loaded factory for unlisted maps
        if explicit_factory:
            return explicit_factory

        pool = self._parse_map_pool()
        if pool:
            pool_factory = pool.get(map_name.lower())
            if pool_factory:
                return pool_factory

        current_factory = self._current_factory()
        if current_factory:
            return current_factory

        self.logger.warning(
            "No factory resolved for map '%s' (not in pool or pool unavailable, and no current factory). "
            "Proceeding without explicit factory.",
            map_name,
        )
        return None

    def _current_factory(self):
        game = self.game
        if not game:
            return None

        try:
            factory = game.factory
        except minqlxtended.NonexistentGameError:
            return None

        return factory.strip() if factory else None

    def _parse_map_pool(self):
        pool_path = self._resolve_map_pool_path()
        if not pool_path:
            self._clear_pool_cache()
            return None

        try:
            pool_mtime = os.path.getmtime(pool_path)
        except OSError as exc:
            self.logger.warning("Could not stat map pool file '%s': %s", pool_path, exc)
            self._clear_pool_cache()
            return None

        if (
            self._cached_pool_data is not None
            and self._cached_pool_path == pool_path
            and self._cached_pool_mtime == pool_mtime
        ):
            return self._cached_pool_data

        parsed = {}
        try:
            with open(pool_path, "r") as pool_file:
                for line_number, raw_line in enumerate(pool_file, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if "|" not in line:
                        self.logger.warning(
                            "Skipping malformed map pool line %d in '%s': missing '|'.",
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
        except OSError as exc:
            self.logger.warning("Could not read map pool file '%s': %s", pool_path, exc)
            self._clear_pool_cache()
            return None

        self._cached_pool_path = pool_path
        self._cached_pool_mtime = pool_mtime
        self._cached_pool_data = parsed
        return parsed

    def _resolve_map_pool_path(self):
        map_pool_cvar = (
            self.get_cvar("sv_mapPoolFile")
            or self.get_cvar("sv_mappoolfile")
            or ""
        ).strip()
        if not map_pool_cvar:
            self.logger.warning("sv_mapPoolFile/sv_mappoolfile is not set.")
            return None

        if os.path.isabs(map_pool_cvar):
            if os.path.isfile(map_pool_cvar):
                return map_pool_cvar
            self.logger.warning("Configured map pool file does not exist: '%s'.", map_pool_cvar)
            return None

        candidates = []
        fs_homepath = self.get_cvar("fs_homepath", str)
        fs_basepath = self.get_cvar("fs_basepath", str)

        if fs_homepath:
            candidates.append(os.path.join(fs_homepath, "baseq3", map_pool_cvar))
            candidates.append(os.path.join(fs_homepath, map_pool_cvar))
        if fs_basepath:
            candidates.append(os.path.join(fs_basepath, "baseq3", map_pool_cvar))
            candidates.append(os.path.join(fs_basepath, map_pool_cvar))

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
        self._cached_pool_mtime = None
        self._cached_pool_data = None