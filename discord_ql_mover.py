import json
import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

import minqlxtended
import minqlxtended.database


def _build_api_url(base, path):
    api_base = str(base or "").strip().rstrip("/")
    while api_base.endswith("/api/v1"):
        api_base = api_base[:-7].rstrip("/")
    api_base += "/api/v1"
    return "{}/{}".format(api_base, str(path or "").lstrip("/"))


class discord_ql_mover(minqlxtended.Plugin):
    database = minqlxtended.database.Redis

    KEY_STEAM_TO_DISCORD = "minqlx:dmover:steam_to_discord:{}"
    KEY_DISCORD_TO_STEAM = "minqlx:dmover:discord_to_steam:{}"
    KEY_DISCORD_NAME = "minqlx:dmover:discord_name:{}"
    KEY_NAME_TO_DISCORD = "minqlx:dmover:discord_name_to_id:{}"
    KEY_LINKS_SET = "minqlx:dmover:links"
    KEY_MINQLX_PLAYER_NAMES = "minqlx:players:{}"

    def __init__(self):
        super().__init__()

        self.set_cvar_once("qlx_fragdex_token_refresh_interval", "3600")
        self.set_cvar_once("qlx_dmoverUseFragdexMappings", "1")
        self.set_cvar_once("qlx_dmoverUseRedisMappingFallback", "0")
        self.set_cvar_once("qlx_dmoverUseCvarDiscordBotToken", "0")
        self.set_cvar_once("qlx_dmoverDiscordBotToken", "")
        self.set_cvar_once("qlx_dmoverDiscordGuildId", "")
        self.set_cvar_once("qlx_dmoverDefaultChannelId", "")
        self.set_cvar_once("qlx_dmoverRedChannelId", "")
        self.set_cvar_once("qlx_dmoverBlueChannelId", "")
        self.set_cvar_once("qlx_dmoverCooldown", "8")
        self.set_cvar_once("qlx_dmoverCommandPermission", "2")
        self.set_cvar_once("qlx_dmoverDryRun", "0")
        self.set_cvar_once("qlx_dmoverRequestTimeoutSeconds", "8")
        self.set_cvar_once("qlx_dmoverSteamApiKey", "")
        self.set_cvar_once("qlx_dmoverAutoMoveTeamsOnCountdown", "1")
        self.set_cvar_once("qlx_dmoverAutoMoveDefaultOnGameEnd", "1")
        self.set_cvar_once("qlx_dmoverAutoMoveTeamsMinInterval", "20")

        self.add_command(("move", "dmove"), self.cmd_move, usage="<teams|default>")
        self.add_command("link", self.cmd_link, usage="<client_id|steam_id> <discord_user_id> [discord_name]")
        self.add_command("unlink", self.cmd_unlink, usage="<client_id|steam_id|discord_user_id>")
        self.add_command("whois", self.cmd_whois, usage="<client_id|steam_id|discord_user_id|discord_name>")
        self.add_command("links", self.cmd_links, usage="[limit]")
        self.add_hook("game_countdown", self.handle_game_countdown)
        self.add_hook("game_end", self.handle_game_end)

        self._last_move_ts = 0.0
        self._last_auto_teams_move_ts = 0.0
        self._cached_discord_bot_token = ""
        self._fragdex_token_refresh_timer = None
        if not self.get_cvar("qlx_dmoverUseCvarDiscordBotToken", bool):
            self._fetch_fragdex_discord_token()
            token_refresh_interval = self.get_cvar("qlx_fragdex_token_refresh_interval", float)
            if token_refresh_interval > 0:
                self._fragdex_token_refresh_timer = self.repeat(
                    token_refresh_interval, self._fetch_fragdex_discord_token
                )
            elif token_refresh_interval < 0:
                self.logger.warning(
                    "Invalid qlx_fragdex_token_refresh_interval %s; token refresh is disabled.",
                    token_refresh_interval,
                )
        self.moved_users_by_bot = set()
        self.active_match_users = self.moved_users_by_bot

    def _discord_bot_token(self):
        if self.get_cvar("qlx_dmoverUseCvarDiscordBotToken", bool):
            raw_token = self.get_cvar("qlx_dmoverDiscordBotToken") or ""
        else:
            raw_token = self._cached_discord_bot_token
        return raw_token, self._normalize_discord_bot_token(raw_token)

    @minqlxtended.thread
    def _fetch_fragdex_discord_token(self):
        api_url = str(self.get_cvar("qlx_fragdexUrl") or "").strip()
        try:
            parsed_url = urlsplit(api_url)
        except ValueError:
            self.logger.warning("Fragdex Discord token fetch failed: invalid qlx_fragdexUrl.")
            return
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            self.logger.warning(
                "Fragdex Discord token fetch failed: qlx_fragdexUrl must be an http:// or https:// URL."
            )
            return

        api_key = str(self.get_cvar("qlx_fragdexKey") or "").strip()
        if not api_key:
            self.logger.warning("Fragdex Discord token fetch failed: qlx_fragdexKey is not configured.")
            return

        token_url = _build_api_url(api_url, "discord/token")
        try:
            request = urllib.request.Request(
                url=token_url,
                headers={"Authorization": "Bearer {}".format(api_key), "Accept": "application/json"},
                method="GET",
            )
        except ValueError:
            self.logger.warning("Fragdex Discord token fetch failed: invalid qlx_fragdexUrl.")
            return
        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(65537)
            if len(body) > 65536:
                self.logger.warning("Fragdex Discord token fetch failed: response was too large.")
                return
            payload = json.loads(body.decode("utf-8"))
            token = payload.get("token") if isinstance(payload, dict) else None
            if not isinstance(token, str):
                self.logger.warning("Fragdex Discord token fetch failed: response did not contain a token.")
                return
            token = self._normalize_discord_bot_token(token or "")
            if not token:
                self.logger.warning("Fragdex Discord token fetch failed: response did not contain a token.")
                return
        except urllib.error.HTTPError as error:
            self.logger.warning("Fragdex Discord token fetch failed: HTTP %s.", error.code)
            return
        except urllib.error.URLError as error:
            self.logger.warning("Fragdex Discord token fetch failed: network error: %s.", error.reason)
            return
        except (UnicodeDecodeError, ValueError):
            self.logger.warning("Fragdex Discord token fetch failed: invalid JSON response.")
            return
        except OSError as error:
            self.logger.warning("Fragdex Discord token fetch failed: request error: %s.", error)
            return

        self._cached_discord_bot_token = token
        self.logger.info("Obtained Discord bot token from Fragdex.")

    # ---------- Commands ----------
    def handle_game_countdown(self):
        if not self.get_cvar("qlx_dmoverAutoMoveTeamsOnCountdown", bool):
            return
        self._move_teams_on_game_countdown()

    @minqlxtended.delay(1)
    @minqlxtended.thread
    def _move_teams_on_game_countdown(self):
        if not self._should_auto_move_teams_now():
            return

        config_error = self._validate_runtime_config()
        if config_error is not None:
            self.msg("^1[DMover]^7 Automatic countdown move skipped: {}".format(config_error))
            return

        self._last_auto_teams_move_ts = time.time()
        self.msg("^2[DMover]^7 Match starting; moving mapped players to their team voice channels.")
        self._execute_move("teams", minqlxtended.CHAT_CHANNEL)

    def _should_auto_move_teams_now(self):
        min_interval = self.get_cvar("qlx_dmoverAutoMoveTeamsMinInterval", float)
        if min_interval <= 0:
            return True

        now = time.time()
        return now >= self._last_auto_teams_move_ts + min_interval

    def handle_game_end(self, aborted):
        if aborted:
            return
        if not self.get_cvar("qlx_dmoverAutoMoveDefaultOnGameEnd", bool):
            return

        teams = self.teams()
        spectator_players = [(player.clean_name, str(player.steam_id)) for player in teams.get("spectator", [])]
        team_snapshot = (
            [(player.clean_name, str(player.steam_id)) for player in teams.get("blue", [])],
            [(player.clean_name, str(player.steam_id)) for player in teams.get("red", [])],
            spectator_players,
        )
        self._move_default_after_game_end(team_snapshot, spectator_players)

    @minqlxtended.delay(2)
    @minqlxtended.thread
    def _move_default_after_game_end(self, team_snapshot, spectator_players):
        config_error = self._validate_runtime_config()
        if config_error is not None:
            self.msg("^1[DMover]^7 Automatic map-end move skipped: {}".format(config_error))
            return

        player_ids = [steam_id for players in team_snapshot for _, steam_id in players]
        discord_mappings = self._get_discord_mappings(player_ids)
        forced_default_discord_ids = self._resolve_forced_spectator_discord_ids(
            spectator_players, discord_mappings
        )
        self.msg("^2[DMover]^7 Map ended; returning tracked match players (and spectators in red/blue voice) to the default voice channel.")
        self._execute_move(
            "default", minqlxtended.CHAT_CHANNEL, team_snapshot, force_move_discord_ids=forced_default_discord_ids,
            discord_mappings=discord_mappings
        )

    def cmd_move(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlxtended.Return.STOP_ALL

        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        action = msg[1].lower()
        if action not in ("teams", "default"):
            channel.reply("^1[DMover]^7 Invalid action. Use ^6teams^7 or ^6default^7.")
            return minqlxtended.Return.STOP_ALL

        bypass_cooldown = self.db.has_permission(player, 5)
        cooldown_seconds = self.get_cvar("qlx_dmoverCooldown", float)
        now = time.time()
        if not bypass_cooldown and now < self._last_move_ts + cooldown_seconds:
            remaining = int((self._last_move_ts + cooldown_seconds) - now)
            if remaining < 1:
                remaining = 1
            channel.reply("^1[DMover]^7 You must wait ^6{}^7 second(s) before moving again.".format(remaining))
            return minqlxtended.Return.STOP_ALL

        config_error = self._validate_runtime_config()
        if config_error is not None:
            channel.reply("^1[DMover]^7 {}".format(config_error))
            return minqlxtended.Return.STOP_ALL

        self._last_move_ts = now
        channel.reply("^2[DMover]^7 Processing ^6{}^7 move...".format(action))
        self._execute_move(action, channel)
        return minqlxtended.Return.STOP_ALL

    def cmd_link(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlxtended.Return.STOP_ALL

        if not self._redis_mapping_commands_enabled():
            channel.reply(
                "^1[DMover]^7 Manage player links in Fragdex, or enable "
                "^6qlx_dmoverUseRedisMappingFallback^7 to store Redis-only fallback links."
            )
            return minqlxtended.Return.STOP_ALL

        if len(msg) < 3:
            return minqlxtended.Return.USAGE

        steam_id = self._resolve_steam_id(msg[1])
        if steam_id is None:
            channel.reply("^1[DMover]^7 Invalid player identifier. Use client id or SteamID64.")
            return minqlxtended.Return.STOP_ALL

        discord_id = self._normalize_discord_id(msg[2])
        if discord_id is None:
            channel.reply("^1[DMover]^7 Invalid Discord user id. It should be numeric.")
            return minqlxtended.Return.STOP_ALL

        discord_name = " ".join(msg[3:]).strip() if len(msg) > 3 else None
        self._set_mapping(steam_id, discord_id, discord_name if discord_name else None)

        if discord_name:
            channel.reply("^2[DMover]^7 Linked steam ^6{}^7 -> discord ^6{}^7 (^6{}^7)."
                          .format(steam_id, discord_id, discord_name))
        else:
            channel.reply("^2[DMover]^7 Linked steam ^6{}^7 -> discord ^6{}^7."
                          .format(steam_id, discord_id))
        return minqlxtended.Return.STOP_ALL

    def cmd_unlink(self, player, msg, channel):
        if not self._require_permission(player, channel):
            return minqlxtended.Return.STOP_ALL

        if not self._redis_mapping_commands_enabled():
            channel.reply(
                "^1[DMover]^7 Manage player links in Fragdex, or enable "
                "^6qlx_dmoverUseRedisMappingFallback^7 to remove Redis-only fallback links."
            )
            return minqlxtended.Return.STOP_ALL

        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        target = msg[1]
        steam_id, discord_id = self._resolve_link_target(target)
        if steam_id is None and discord_id is None:
            channel.reply("^1[DMover]^7 No mapping found for ^6{}^7.".format(target))
            return minqlxtended.Return.STOP_ALL

        if steam_id is None and discord_id is not None:
            steam_id = self._get_redis_steam_by_discord(discord_id)
        if discord_id is None and steam_id is not None:
            discord_id = self._get_redis_discord_by_steam(steam_id)

        if steam_id is None or discord_id is None:
            channel.reply("^1[DMover]^7 Incomplete mapping detected; cannot unlink safely.")
            return minqlxtended.Return.STOP_ALL

        self._delete_mapping(steam_id, discord_id)
        channel.reply("^2[DMover]^7 Unlinked steam ^6{}^7 and discord ^6{}^7.".format(steam_id, discord_id))
        return minqlxtended.Return.STOP_ALL

    def cmd_whois(self, player, msg, channel):
        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        target = msg[1]
        steam_id = self._resolve_steam_id(target)
        is_client_id = target.isdigit() and int(target) < 64
        self._whois_background(target, steam_id, is_client_id, channel)
        return minqlxtended.Return.STOP_ALL

    @minqlxtended.thread
    def _whois_background(self, target, steam_id, is_client_id, channel):
        discord_id = self._get_discord_by_steam(steam_id) if steam_id is not None else None
        if discord_id is None and not is_client_id:
            discord_id = self._normalize_discord_id(target)
            if discord_id is None:
                discord_id = self._get_discord_by_name(target)
            if discord_id is not None:
                steam_id = self._get_steam_by_discord(discord_id)
                if steam_id is None:
                    discord_id = None
        elif discord_id is None:
            steam_id = None
        if discord_id is None and steam_id is None:
            self._reply_whois_mapping(channel, target, None, None, None)
            return

        discord_name = self._get_discord_name(discord_id) if discord_id is not None else None
        self._reply_whois_mapping(channel, target, steam_id, discord_id, discord_name)
        if steam_id is not None:
            self._append_whois_steam_persona_name(steam_id, channel)

    @minqlxtended.next_frame
    def _reply_whois_mapping(self, channel, target, steam_id, discord_id, discord_name):
        if steam_id is None and discord_id is None:
            channel.reply("^1[DMover]^7 No mapping found for ^6{}^7.".format(target))
        elif discord_name:
            channel.reply("^2[DMover]^7 steam ^6{}^7 <-> discord ^6{}^7 (^6{}^7)."
                          .format(steam_id, discord_id, discord_name))
        else:
            channel.reply("^2[DMover]^7 steam ^6{}^7 <-> discord ^6{}^7."
                          .format(steam_id, discord_id))

    @minqlxtended.thread
    def _append_whois_steam_persona_name(self, steam_id, channel):
        persona_name = self._resolve_steam_persona_name(steam_id)
        if persona_name is None:
            return
        self._reply_whois_steam_persona_name(channel, persona_name)

    @minqlxtended.next_frame
    def _reply_whois_steam_persona_name(self, channel, persona_name):
        channel.reply("^2[DMover]^7 Steam persona: ^6{}^7.".format(persona_name))

    def _resolve_steam_persona_name(self, steam_id):
        try:
            sid = int(steam_id)
        except (TypeError, ValueError):
            self.logger.warning("Failed to resolve Steam persona: invalid steam id '%s'.", steam_id)
            return None

        connected_player = self.player(sid)
        if connected_player is not None:
            return connected_player.clean_name

        cached_name = self._resolve_cached_player_name(sid)
        if cached_name is not None:
            return cached_name

        return self._resolve_steam_name_from_api(sid)

    def _resolve_cached_player_name(self, steam_id):
        key = self.KEY_MINQLX_PLAYER_NAMES.format(steam_id)
        if key not in self.db:
            return None

        recent_names = self.db.lrange(key, 0, 0)
        if not recent_names:
            return None

        cached_name = self.clean_text(self._decode(recent_names[0])).strip()
        if not cached_name:
            return None

        return cached_name

    def _resolve_steam_name_from_api(self, steam_id):
        steam_api_key = self.get_cvar("qlx_dmoverSteamApiKey")
        if not steam_api_key:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: missing qlx_dmoverSteamApiKey and no local name cache.",
                steam_id,
            )
            return None

        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)
        url = (
            "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
            "?key={}&steamids={}".format(steam_api_key, steam_id)
        )

        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as err:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: Steam API HTTP %s.",
                steam_id,
                err.code,
            )
            return None
        except urllib.error.URLError as err:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: Steam API network error: %s.",
                steam_id,
                err.reason,
            )
            return None
        except ValueError:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: invalid Steam API JSON response.",
                steam_id,
            )
            return None

        players = payload.get("response", {}).get("players", [])
        if not players:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: Steam API returned no player record.",
                steam_id,
            )
            return None

        persona_name = players[0].get("personaname")
        if persona_name is None:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: Steam API response missing personaname.",
                steam_id,
            )
            return None

        clean_persona_name = self.clean_text(str(persona_name)).strip()
        if not clean_persona_name:
            self.logger.warning(
                "Failed to resolve Steam persona for %s: Steam API returned blank personaname.",
                steam_id,
            )
            return None

        return clean_persona_name

    def cmd_links(self, player, msg, channel):
        if not self._redis_mapping_commands_enabled():
            channel.reply(
                "^1[DMover]^7 Redis mappings are disabled; manage player links in Fragdex or enable "
                "^6qlx_dmoverUseRedisMappingFallback^7."
            )
            return minqlxtended.Return.STOP_ALL

        limit = 20
        if len(msg) > 1:
            try:
                limit = int(msg[1])
            except ValueError:
                channel.reply("^1[DMover]^7 Invalid limit.")
                return minqlxtended.Return.STOP_ALL
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100

        steam_ids = sorted([self._decode(v) for v in self.db.smembers(self.KEY_LINKS_SET)])
        if not steam_ids:
            channel.reply("^3[DMover]^7 No mappings stored.")
            return minqlxtended.Return.STOP_ALL

        channel.reply("^3[DMover]^7 Showing {} of {} links:".format(min(limit, len(steam_ids)), len(steam_ids)))
        for steam_id in steam_ids[:limit]:
            discord_id = self._get_redis_discord_by_steam(steam_id)
            if discord_id is None:
                continue
            discord_name = self._get_redis_discord_name(discord_id)
            if discord_name:
                channel.reply("  ^6{}^7 -> ^6{}^7 (^6{}^7)".format(steam_id, discord_id, discord_name))
            else:
                channel.reply("  ^6{}^7 -> ^6{}^7".format(steam_id, discord_id))
        return minqlxtended.Return.STOP_ALL

    # ---------- Move flow ----------
    @minqlxtended.thread
    def _execute_move(self, action, channel, team_snapshot=None, force_move_discord_ids=None, discord_mappings=None):
        raw_token, token = self._discord_bot_token()
        auth_diagnostics = self._discord_auth_diagnostics(raw_token, token)
        guild_id = self.get_cvar("qlx_dmoverDiscordGuildId")
        default_channel = self.get_cvar("qlx_dmoverDefaultChannelId")
        red_channel = self.get_cvar("qlx_dmoverRedChannelId")
        blue_channel = self.get_cvar("qlx_dmoverBlueChannelId")
        dry_run = self.get_cvar("qlx_dmoverDryRun", bool)

        if force_move_discord_ids is None:
            force_move_discord_ids = set()

        if team_snapshot is None:
            teams = self.teams()
            blue_players = [(player.clean_name, str(player.steam_id)) for player in teams.get("blue", [])]
            red_players = [(player.clean_name, str(player.steam_id)) for player in teams.get("red", [])]
            spectator_players = []
        else:
            if len(team_snapshot) == 3:
                blue_players, red_players, spectator_players = team_snapshot
            else:
                blue_players, red_players = team_snapshot
                spectator_players = []

        if discord_mappings is None:
            player_ids = [steam_id for players in (blue_players, red_players) for _, steam_id in players]
            if action == "default":
                player_ids.extend(steam_id for _, steam_id in spectator_players)
            discord_mappings = self._get_discord_mappings(player_ids)

        if action == "teams":
            self.active_match_users.clear()

        moved = []
        missing = []
        failed = []
        skipped_untracked = []
        skipped_wrong_channel = []

        for player_name, steam_id in blue_players:
            target_channel = blue_channel if action == "teams" else default_channel
            self._move_player(
                action, player_name, steam_id, guild_id, token, target_channel, default_channel, red_channel,
                blue_channel, dry_run, moved, missing, failed, skipped_untracked, skipped_wrong_channel,
                force_move_discord_ids, auth_diagnostics, discord_mappings
            )

        for player_name, steam_id in red_players:
            target_channel = red_channel if action == "teams" else default_channel
            self._move_player(
                action, player_name, steam_id, guild_id, token, target_channel, default_channel, red_channel,
                blue_channel, dry_run, moved, missing, failed, skipped_untracked, skipped_wrong_channel,
                force_move_discord_ids, auth_diagnostics, discord_mappings
            )

        if action == "default":
            for player_name, steam_id in spectator_players:
                self._move_player(
                    action, player_name, steam_id, guild_id, token, default_channel, default_channel, red_channel,
                    blue_channel, dry_run, moved, missing, failed, skipped_untracked, skipped_wrong_channel,
                    force_move_discord_ids, auth_diagnostics, discord_mappings
                )

        self._report_move_result(
            action, channel, moved, missing, failed, skipped_untracked, skipped_wrong_channel, dry_run
        )
        if action == "default":
            self.active_match_users.clear()

    def _move_player(
        self, action, player_name, steam_id, guild_id, token, target_channel, default_channel, red_channel,
        blue_channel, dry_run, moved, missing, failed, skipped_untracked, skipped_wrong_channel,
        force_move_discord_ids, auth_diagnostics, discord_mappings
    ):
        discord_id = discord_mappings.get(str(steam_id))
        if discord_id is None:
            missing.append((player_name, steam_id))
            return

        force_move = action == "default" and discord_id in force_move_discord_ids
        if action == "default" and discord_id not in self.active_match_users and not force_move:
            skipped_untracked.append((player_name, steam_id, discord_id))
            return

        ok, status, source_channel, body, voice_url = self._discord_get_member_voice_channel(
            guild_id, discord_id, token
        )
        if not ok:
            self._log_discord_request_failure(
                "voice_state_lookup", "GET", voice_url, guild_id, discord_id, target_channel,
                status, body, auth_diagnostics, "voice-state lookup failed; no move preflight completed"
            )
            failed.append((player_name, steam_id, discord_id, status, body))
            return

        if action == "teams":
            if source_channel != str(default_channel):
                skipped_wrong_channel.append((player_name, steam_id, discord_id, source_channel, "teams"))
                return
            source_channel_check = "source_channel_matches_default"
        elif source_channel not in (str(red_channel), str(blue_channel)):
            skipped_wrong_channel.append((player_name, steam_id, discord_id, source_channel, "default"))
            return
        else:
            source_channel_check = "source_channel_matches_red_or_blue"

        if dry_run:
            moved.append((player_name, steam_id, discord_id, "dry-run"))
            return

        ok, status, body, move_url = self._discord_move_member(guild_id, discord_id, target_channel, token)
        if ok:
            moved.append((player_name, steam_id, discord_id, str(status)))
            if action == "teams":
                self.active_match_users.add(discord_id)
            elif action == "default":
                self.active_match_users.discard(discord_id)
        else:
            preflight = (
                "voice_state_lookup_succeeded; source_channel_id={}; {}; "
                "bot_permissions=not_checked; role_hierarchy=not_checked"
            ).format(source_channel, source_channel_check)
            self._log_discord_request_failure(
                "member_move", "PATCH", move_url, guild_id, discord_id, target_channel,
                status, body, auth_diagnostics, preflight
            )
            failed.append((player_name, steam_id, discord_id, status, body))

    def _resolve_forced_spectator_discord_ids(self, spectator_players, discord_mappings):
        forced_ids = set()
        for _, steam_id in spectator_players:
            discord_id = discord_mappings.get(str(steam_id))
            if discord_id is not None:
                forced_ids.add(discord_id)
        return forced_ids

    def _discord_get_member_voice_channel(self, guild_id, discord_id, token):
        url = "https://discord.com/api/v10/guilds/{}/voice-states/{}".format(guild_id, discord_id)
        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)

        ok, status, body = self._discord_get_json(url, token, timeout_seconds)
        if not ok:
            if status == 404:
                return True, status, None, "", url
            return False, status, None, body, url

        channel_id = body.get("channel_id")
        if channel_id is None:
            return True, status, None, "", url
        return True, status, str(channel_id), "", url

    def _discord_get_json(self, url, token, timeout_seconds):
        headers = {
            "Authorization": self._discord_authorization_header(token),
            "User-Agent": "discord-ql-mover/1.0",
        }

        request = urllib.request.Request(url=url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                payload = json.load(response)
                return True, int(status), payload
        except urllib.error.HTTPError as err:
            status = int(err.code)
            body = err.read().decode("utf-8", errors="replace")
            if status == 429:
                retry_seconds = self._parse_retry_after(body)
                if retry_seconds is not None and retry_seconds <= 10:
                    time.sleep(retry_seconds)
                    try:
                        with urllib.request.urlopen(request, timeout=timeout_seconds) as retry_response:
                            retry_status = getattr(retry_response, "status", 200)
                            retry_payload = json.load(retry_response)
                            return True, int(retry_status), retry_payload
                    except urllib.error.HTTPError as retry_err:
                        retry_body = retry_err.read().decode("utf-8", errors="replace")
                        return False, int(retry_err.code), retry_body
                    except urllib.error.URLError as retry_err:
                        return False, -1, str(retry_err.reason)
                    except ValueError:
                        return False, -1, "Invalid Discord JSON response."
            return False, status, body
        except urllib.error.URLError as err:
            return False, -1, str(err.reason)
        except ValueError:
            return False, -1, "Invalid Discord JSON response."

    def _discord_move_member(self, guild_id, discord_id, channel_id, token):
        payload = json.dumps({"channel_id": str(channel_id)}).encode("utf-8")
        url = "https://discord.com/api/v10/guilds/{}/members/{}".format(guild_id, discord_id)
        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)

        ok, status, body = self._patch_discord_member(url, payload, token, timeout_seconds)
        return ok, status, body, url

    def _patch_discord_member(self, url, payload, token, timeout_seconds):
        headers = {
            "Authorization": self._discord_authorization_header(token),
            "Content-Type": "application/json",
            "User-Agent": "discord-ql-mover/1.0",
        }

        request = urllib.request.Request(url=url, data=payload, headers=headers, method="PATCH")
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                return True, int(status), ""
        except urllib.error.HTTPError as err:
            status = int(err.code)
            body = err.read().decode("utf-8", errors="replace")
            if status == 429:
                retry_seconds = self._parse_retry_after(body)
                if retry_seconds is not None and retry_seconds <= 10:
                    time.sleep(retry_seconds)
                    try:
                        with urllib.request.urlopen(request, timeout=timeout_seconds) as retry_response:
                            retry_status = getattr(retry_response, "status", 200)
                            return True, int(retry_status), ""
                    except urllib.error.HTTPError as retry_err:
                        retry_body = retry_err.read().decode("utf-8", errors="replace")
                        return False, int(retry_err.code), retry_body
                    except urllib.error.URLError as retry_err:
                        return False, -1, str(retry_err.reason)
            return False, status, body
        except urllib.error.URLError as err:
            return False, -1, str(err.reason)

    def _normalize_discord_bot_token(self, raw_token):
        token = str(raw_token).strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
            token = token[1:-1].strip()
        return token

    def _discord_authorization_header(self, token):
        return "Bot {}".format(token)

    def _discord_auth_diagnostics(self, raw_token, token):
        raw_token = str(raw_token)
        return {
            "authorization_header_present": bool(self._discord_authorization_header(token)),
            "authorization_prefix": "Bot",
            "token_raw_length": len(raw_token),
            "token_effective_length": len(token),
            "token_normalized": raw_token != token,
        }

    def _log_discord_request_failure(
        self, stage, method, url, guild_id, discord_id, target_channel, status, body, auth_diagnostics, preflight
    ):
        self.logger.warning(
            "[DMover] Discord request failed stage=%s method=%s status=%s url=%s "
            "guild_id=%s user_id=%s target_channel_id=%s "
            "authorization_header_present=%s authorization_prefix=%s "
            "token_raw_length=%s token_effective_length=%s token_normalized=%s "
            "preflight=%s body=%s",
            stage,
            method,
            status,
            url,
            guild_id,
            discord_id,
            target_channel,
            auth_diagnostics["authorization_header_present"],
            auth_diagnostics["authorization_prefix"],
            auth_diagnostics["token_raw_length"],
            auth_diagnostics["token_effective_length"],
            auth_diagnostics["token_normalized"],
            preflight,
            (body or "")[:300],
        )

    def _parse_retry_after(self, body):
        try:
            payload = json.loads(body)
        except ValueError:
            return None

        retry_after = payload.get("retry_after")
        if retry_after is None:
            return None
        try:
            value = float(retry_after)
        except (TypeError, ValueError):
            return None

        if value < 0:
            return None
        return value

    @minqlxtended.next_frame
    def _report_move_result(
        self, action, channel, moved, missing, failed, skipped_untracked, skipped_wrong_channel, dry_run
    ):
        mode = "DRY-RUN " if dry_run else ""
        channel.reply(
            "^2[DMover]^7 {}{} completed. moved:^6{}^7 missing-link:^6{}^7 skipped-untracked:^6{}^7 "
            "skipped-wrong-channel:^6{}^7 failed:^6{}^7"
            .format(
                mode, action, len(moved), len(missing), len(skipped_untracked), len(skipped_wrong_channel),
                len(failed)
            )
        )

        if missing:
            missing_names = ", ".join(["{}({})".format(name, steam_id) for name, steam_id in missing[:8]])
            channel.reply("^3[DMover]^7 Missing links: {}".format(missing_names))

        if skipped_untracked:
            skipped_names = ", ".join(
                ["{}({})".format(name, steam_id) for name, steam_id, _ in skipped_untracked[:8]]
            )
            channel.reply("^3[DMover]^7 Skipped untracked players: {}".format(skipped_names))

        if skipped_wrong_channel:
            skipped_names = ", ".join(
                ["{}({})".format(name, steam_id) for name, steam_id, _, _, _ in skipped_wrong_channel[:8]]
            )
            channel.reply("^3[DMover]^7 Skipped due to source channel rules: {}".format(skipped_names))

        if failed:
            first = failed[0]
            channel.reply("^1[DMover]^7 Discord move failure example: {}({}) -> {} status={} body={}"
                          .format(first[0], first[1], first[2], first[3], first[4][:120]))

    # ---------- Mapping ----------
    def _set_mapping(self, steam_id, discord_id, discord_name=None):
        old_discord = self._get_redis_discord_by_steam(steam_id)
        if old_discord is not None and old_discord != discord_id:
            self._delete_mapping(steam_id, old_discord)

        old_steam = self._get_redis_steam_by_discord(discord_id)
        if old_steam is not None and old_steam != steam_id:
            self._delete_mapping(old_steam, discord_id)

        self.db[self.KEY_STEAM_TO_DISCORD.format(steam_id)] = str(discord_id)
        self.db[self.KEY_DISCORD_TO_STEAM.format(discord_id)] = str(steam_id)
        self.db.sadd(self.KEY_LINKS_SET, str(steam_id))

        if discord_name:
            self._set_discord_name(discord_id, discord_name)

    def _delete_mapping(self, steam_id, discord_id):
        steam_key = self.KEY_STEAM_TO_DISCORD.format(steam_id)
        discord_key = self.KEY_DISCORD_TO_STEAM.format(discord_id)
        name_key = self.KEY_DISCORD_NAME.format(discord_id)

        if steam_key in self.db:
            del self.db[steam_key]
        if discord_key in self.db:
            del self.db[discord_key]

        if name_key in self.db:
            discord_name = self._decode(self.db[name_key])
            del self.db[name_key]
            normalized_name = self._normalize_discord_name(discord_name)
            if normalized_name:
                name_index_key = self.KEY_NAME_TO_DISCORD.format(normalized_name)
                if name_index_key in self.db:
                    existing = self._decode(self.db[name_index_key])
                    if existing == str(discord_id):
                        del self.db[name_index_key]

        self.db.srem(self.KEY_LINKS_SET, str(steam_id))

    def _set_discord_name(self, discord_id, discord_name):
        discord_name = discord_name.strip()
        if not discord_name:
            return

        old_name = self._get_redis_discord_name(discord_id)
        if old_name is not None:
            old_norm = self._normalize_discord_name(old_name)
            if old_norm:
                old_key = self.KEY_NAME_TO_DISCORD.format(old_norm)
                if old_key in self.db:
                    existing = self._decode(self.db[old_key])
                    if existing == str(discord_id):
                        del self.db[old_key]

        self.db[self.KEY_DISCORD_NAME.format(discord_id)] = discord_name
        normalized = self._normalize_discord_name(discord_name)
        if normalized:
            self.db[self.KEY_NAME_TO_DISCORD.format(normalized)] = str(discord_id)

    def _resolve_link_target(self, token):
        steam_id = self._resolve_steam_id(token)
        if steam_id is not None and self._get_redis_discord_by_steam(steam_id) is not None:
            return steam_id, None

        discord_id = self._normalize_discord_id(token)
        if discord_id is not None and self._get_redis_steam_by_discord(discord_id) is not None:
            return None, discord_id

        return None, None

    def _resolve_steam_id(self, token):
        try:
            value = int(token)
        except ValueError:
            return None

        if 0 <= value < 64:
            try:
                target = self.player(value)
            except minqlxtended.NonexistentPlayerError:
                return None
            if target is None:
                return None
            return str(target.steam_id)

        if value >= 64:
            return str(value)
        return None

    def _normalize_discord_id(self, token):
        if not token.isdigit():
            return None
        return token

    def _normalize_discord_name(self, name):
        normalized = name.strip().lower()
        if not normalized:
            return None
        return normalized

    def _get_discord_by_steam(self, steam_id):
        if not self._fragdex_mapping_source_enabled():
            return self._get_redis_discord_by_steam(steam_id)

        data, error = self._fragdex_api_request(
            "/players/{}".format(urllib.parse.quote(str(steam_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex mapping lookup failed for Steam ID %s: %s.", steam_id, error)
        else:
            discord_id = data.get("discord_id")
            if isinstance(discord_id, str) and discord_id.isdigit():
                return discord_id
            self.logger.warning("Fragdex has no Discord mapping for Steam ID %s.", steam_id)
        if self._redis_mapping_fallback_enabled():
            return self._get_redis_discord_by_steam(steam_id)
        return None

    def _get_steam_by_discord(self, discord_id):
        if not self._fragdex_mapping_source_enabled():
            return self._get_redis_steam_by_discord(discord_id)

        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex mapping lookup failed for Discord ID %s: %s.", discord_id, error)
        else:
            players = data.get("players")
            if isinstance(players, list):
                matches = [p for p in players if isinstance(p, dict) and p.get("steam_id")]
                if len(matches) == 1:
                    return str(matches[0]["steam_id"])
                if len(matches) > 1:
                    self.logger.warning(
                        "Fragdex returned multiple Steam mappings for Discord ID %s; skipping ambiguous lookup.",
                        discord_id,
                    )
                else:
                    self.logger.warning("Fragdex has no Steam mapping for Discord ID %s.", discord_id)
            else:
                self.logger.warning("Fragdex returned an invalid Discord lookup response.")
        if self._redis_mapping_fallback_enabled():
            return self._get_redis_steam_by_discord(discord_id)
        return None

    def _get_discord_name(self, discord_id):
        if not self._fragdex_mapping_source_enabled():
            return self._get_redis_discord_name(discord_id)

        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex name lookup failed for Discord ID %s: %s.", discord_id, error)
        else:
            players = data.get("players")
            if not isinstance(players, list):
                self.logger.warning("Fragdex returned an invalid Discord name lookup response.")
            elif players:
                name = players[0].get("discord_name") if isinstance(players[0], dict) else None
                if isinstance(name, str) and name:
                    return name
        if self._redis_mapping_fallback_enabled():
            return self._get_redis_discord_name(discord_id)
        return None

    def _get_discord_by_name(self, discord_name):
        if not self._fragdex_mapping_source_enabled():
            return self._get_redis_discord_by_name(discord_name)

        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_name), safe=""))
        )
        if error:
            self.logger.warning("Fragdex name lookup failed for %s: %s.", discord_name, error)
        else:
            players = data.get("players")
            if not isinstance(players, list):
                self.logger.warning("Fragdex returned an invalid Discord name lookup response.")
            else:
                ids = {
                    p["discord_id"] for p in players
                    if isinstance(p, dict) and isinstance(p.get("discord_id"), str) and p["discord_id"]
                }
                if len(ids) == 1:
                    return next(iter(ids))
                if len(ids) > 1:
                    self.logger.warning("Fragdex returned multiple Discord accounts matching %s.", discord_name)
                else:
                    self.logger.warning("Fragdex has no mapping for Discord name %s.", discord_name)
        if self._redis_mapping_fallback_enabled():
            return self._get_redis_discord_by_name(discord_name)
        return None

    def _fragdex_api_request(self, path, body=None):
        api_url = str(self.get_cvar("qlx_fragdexUrl") or "").strip().rstrip("/")
        try:
            parsed_url = urlsplit(api_url)
        except ValueError:
            return None, "invalid qlx_fragdexUrl"
        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
        ):
            return None, "qlx_fragdexUrl must be an http:// or https:// URL"

        api_key = str(self.get_cvar("qlx_fragdexKey") or "").strip()
        if not api_key:
            return None, "qlx_fragdexKey is not configured"

        timeout_seconds = self.get_cvar("qlx_dmoverRequestTimeoutSeconds", float)
        try:
            request_body = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Authorization": "Bearer {}".format(api_key), "Accept": "application/json"}
            if request_body is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                url=_build_api_url(api_url, path), data=request_body, headers=headers,
                method="POST" if request_body is not None else "GET",
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(262145)
            if len(body) > 262144:
                return None, "response was too large"
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                return None, "invalid JSON response"
            return payload, None
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            suffix = " (retry after {}s)".format(retry_after) if retry_after else ""
            return None, "HTTP {}{}".format(error.code, suffix)
        except urllib.error.URLError as error:
            return None, "network error: {}".format(error.reason)
        except (OSError, UnicodeDecodeError, ValueError) as error:
            return None, "request failed: {}".format(error)

    def _get_discord_mappings(self, steam_ids):
        ids = list(dict.fromkeys(str(steam_id) for steam_id in steam_ids))
        if not self._fragdex_mapping_source_enabled():
            return {
                steam_id: discord_id
                for steam_id in ids
                if (discord_id := self._get_redis_discord_by_steam(steam_id)) is not None
            }

        mappings = {}
        for offset in range(0, len(ids), 100):
            batch = ids[offset:offset + 100]
            data, error = self._fragdex_api_request("/players/lookup", {"steam_ids": batch})
            if error:
                self.logger.warning("Fragdex batch mapping lookup failed: %s.", error)
                if self._redis_mapping_fallback_enabled():
                    for steam_id in batch:
                        discord_id = self._get_redis_discord_by_steam(steam_id)
                        if discord_id is not None:
                            mappings[steam_id] = discord_id
                continue

            players = data.get("players")
            if not isinstance(players, list):
                self.logger.warning("Fragdex returned an invalid batch mapping response.")
                if self._redis_mapping_fallback_enabled():
                    for steam_id in batch:
                        discord_id = self._get_redis_discord_by_steam(steam_id)
                        if discord_id is not None:
                            mappings[steam_id] = discord_id
                continue

            results = {
                player.get("steam_id"): player
                for player in players
                if isinstance(player, dict) and isinstance(player.get("steam_id"), str)
            }
            for steam_id in batch:
                player = results.get(steam_id)
                discord_id = player.get("discord_id") if player else None
                if isinstance(discord_id, str) and discord_id.isdigit():
                    mappings[steam_id] = discord_id
                    continue

                self.logger.warning("Fragdex has no Discord mapping for Steam ID %s.", steam_id)
                if self._redis_mapping_fallback_enabled():
                    fallback_discord_id = self._get_redis_discord_by_steam(steam_id)
                    if fallback_discord_id is not None:
                        mappings[steam_id] = fallback_discord_id
        return mappings

    def _redis_mapping_fallback_enabled(self):
        return self.get_cvar("qlx_dmoverUseRedisMappingFallback", bool)

    def _fragdex_mapping_source_enabled(self):
        return self.get_cvar("qlx_dmoverUseFragdexMappings", bool)

    def _redis_mapping_commands_enabled(self):
        return (
            not self._fragdex_mapping_source_enabled()
            or self._redis_mapping_fallback_enabled()
        )

    def _get_redis_discord_by_steam(self, steam_id):
        key = self.KEY_STEAM_TO_DISCORD.format(steam_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_redis_steam_by_discord(self, discord_id):
        key = self.KEY_DISCORD_TO_STEAM.format(discord_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_redis_discord_name(self, discord_id):
        key = self.KEY_DISCORD_NAME.format(discord_id)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _get_redis_discord_by_name(self, discord_name):
        normalized = self._normalize_discord_name(discord_name)
        if normalized is None:
            return None
        key = self.KEY_NAME_TO_DISCORD.format(normalized)
        if key not in self.db:
            return None
        return self._decode(self.db[key])

    def _decode(self, value):
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    # ---------- Validation / permissions ----------
    def _validate_runtime_config(self):
        _, token = self._discord_bot_token()
        guild_id = self.get_cvar("qlx_dmoverDiscordGuildId")
        default_channel = self.get_cvar("qlx_dmoverDefaultChannelId")
        red_channel = self.get_cvar("qlx_dmoverRedChannelId")
        blue_channel = self.get_cvar("qlx_dmoverBlueChannelId")

        if not token:
            if self.get_cvar("qlx_dmoverUseCvarDiscordBotToken", bool):
                return "Missing qlx_dmoverDiscordBotToken while qlx_dmoverUseCvarDiscordBotToken is enabled."
            return "Discord bot token has not been obtained from Fragdex."
        if not guild_id:
            return "Missing qlx_dmoverDiscordGuildId."
        if not default_channel:
            return "Missing qlx_dmoverDefaultChannelId."
        if not red_channel:
            return "Missing qlx_dmoverRedChannelId."
        if not blue_channel:
            return "Missing qlx_dmoverBlueChannelId."

        return None

    def _require_permission(self, player, channel):
        required = self.get_cvar("qlx_dmoverCommandPermission", int)
        if self.db.has_permission(player, required):
            return True
        channel.reply("^1[DMover]^7 You need permission level ^6{}^7.".format(required))
        return False
