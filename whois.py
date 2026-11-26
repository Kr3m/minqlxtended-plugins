"""
whois - standalone !whois for minqlxtended, backed by Fragdex.

Ported from discord_ql_mover.py so the command works without the mover plugin.

    !whois <client_id|steam_id|discord_user_id|discord_name>

Resolves a Steam <-> Discord link through Fragdex and replies with the
mapping plus the player's Steam persona name.

Config (shared with fragdex.py / discord_ql_mover.py, no new cvars):
    qlx_fragdexUrl  - Fragdex base URL (with or without /api/v1)
    qlx_fragdexKey  - Fragdex API key
"""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

import minqlxtended

REQUEST_TIMEOUT_SECONDS = 8.0
MAX_RESPONSE_BYTES = 262144
TAG_OK = "^2[DMover]^7"
TAG_ERR = "^1[DMover]^7"


def _build_api_url(base, path):
    api_base = str(base or "").strip().rstrip("/")
    while api_base.endswith("/api/v1"):
        api_base = api_base[:-7].rstrip("/")
    api_base += "/api/v1"
    return "{}/{}".format(api_base, str(path or "").lstrip("/"))


class whois(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()
        # Same cvars fragdex.py registers; set_cvar_once never overwrites an existing value.
        self.set_cvar_once("qlx_fragdexUrl", "")
        self.set_cvar_once("qlx_fragdexKey", "")

        self.add_command("whois", self.cmd_whois, usage="<client_id|steam_id|discord_user_id|discord_name>")

    # ---------- Command ----------
    def cmd_whois(self, player, msg, channel):
        if len(msg) < 2:
            return minqlxtended.Return.USAGE

        config_error = self._fragdex_config_error()
        if config_error:
            self.logger.warning("!whois unavailable: %s.", config_error)
            channel.reply("{} Fragdex is not configured; whois is unavailable.".format(TAG_ERR))
            return minqlxtended.Return.STOP_ALL

        target = msg[1]
        steam_id = self._resolve_steam_id(target)
        is_client_id = target.isdigit() and int(target) < 64
        self._whois_background(target, steam_id, is_client_id, channel)
        return minqlxtended.Return.STOP_ALL

    @minqlxtended.thread
    def _whois_background(self, target, steam_id, is_client_id, channel):
        try:
            self._do_whois(target, steam_id, is_client_id, channel)
        except Exception:  # never let a bad response kill the worker silently
            self.logger.exception("Unexpected error during !whois %s.", target)
            self._reply(channel, "{} Whois lookup failed.".format(TAG_ERR))

    def _do_whois(self, target, steam_id, is_client_id, channel):
        failed = False
        discord_id = None
        if steam_id is not None:
            discord_id, err = self._get_discord_by_steam(steam_id)
            failed |= err
        if discord_id is None and not is_client_id:
            discord_id = self._normalize_discord_id(target)
            if discord_id is None:
                discord_id, err = self._get_discord_by_name(target)
                failed |= err
            if discord_id is not None:
                steam_id, err = self._get_steam_by_discord(discord_id)
                failed |= err
                if steam_id is None:
                    discord_id = None
        elif discord_id is None:
            steam_id = None

        if discord_id is None and steam_id is None:
            if failed:
                self._reply(channel, "{} Fragdex lookup failed for ^6{}^7; try again later.".format(TAG_ERR, target))
            else:
                self._reply_whois_mapping(channel, target, None, None, None)
            return

        discord_name = self._get_discord_name(discord_id) if discord_id is not None else None
        self._reply_whois_mapping(channel, target, steam_id, discord_id, discord_name)
        if steam_id is not None:
            persona_name = self._resolve_steam_persona_name(steam_id)
            self._reply(channel, "{} Steam persona: ^6{}^7.".format(TAG_OK, persona_name or "unavailable"))

    def _reply_whois_mapping(self, channel, target, steam_id, discord_id, discord_name):
        if steam_id is None and discord_id is None:
            self._reply(channel, "{} No mapping found for ^6{}^7.".format(TAG_ERR, target))
        elif discord_name:
            self._reply(channel, "{} steam ^6{}^7 <-> discord ^6{}^7 (^6{}^7)."
                        .format(TAG_OK, steam_id, discord_id, discord_name))
        else:
            self._reply(channel, "{} steam ^6{}^7 <-> discord ^6{}^7."
                        .format(TAG_OK, steam_id, discord_id))

    @minqlxtended.next_frame
    def _reply(self, channel, text):
        channel.reply(text)

    # ---------- Target parsing ----------
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

    # ---------- Fragdex lookups (worker thread only) ----------
    # Lookup helpers return (value, request_failed) so the caller can tell
    # "Fragdex said no mapping" apart from "Fragdex could not be reached".

    def _get_discord_by_steam(self, steam_id):
        data, error = self._fragdex_api_request(
            "/players/{}".format(urllib.parse.quote(str(steam_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex mapping lookup failed for Steam ID %s: %s.", steam_id, error)
            # 404 means Fragdex has never seen this Steam ID: a clean "no mapping".
            return None, not error.startswith("HTTP 404")
        discord_id = data.get("discord_id")
        if isinstance(discord_id, str) and discord_id.isdigit():
            return discord_id, False
        self.logger.warning("Fragdex has no Discord mapping for Steam ID %s.", steam_id)
        return None, False

    def _get_steam_by_discord(self, discord_id):
        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex mapping lookup failed for Discord ID %s: %s.", discord_id, error)
            return None, True
        players = data.get("players")
        if not isinstance(players, list):
            self.logger.warning("Fragdex returned an invalid Discord lookup response.")
            return None, True
        matches = [p for p in players if isinstance(p, dict) and p.get("steam_id")]
        if len(matches) == 1:
            return str(matches[0]["steam_id"]), False
        if len(matches) > 1:
            self.logger.warning(
                "Fragdex returned multiple Steam mappings for Discord ID %s; skipping ambiguous lookup.",
                discord_id,
            )
        else:
            self.logger.warning("Fragdex has no Steam mapping for Discord ID %s.", discord_id)
        return None, False

    def _get_discord_name(self, discord_id):
        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_id), safe=""))
        )
        if error:
            self.logger.warning("Fragdex name lookup failed for Discord ID %s: %s.", discord_id, error)
            return None
        players = data.get("players")
        if not isinstance(players, list):
            self.logger.warning("Fragdex returned an invalid Discord name lookup response.")
        elif players:
            name = players[0].get("discord_name") if isinstance(players[0], dict) else None
            if isinstance(name, str) and name:
                return name
        return None

    def _get_discord_by_name(self, discord_name):
        data, error = self._fragdex_api_request(
            "/discord/{}".format(urllib.parse.quote(str(discord_name), safe=""))
        )
        if error:
            self.logger.warning("Fragdex name lookup failed for %s: %s.", discord_name, error)
            # 400 = Fragdex rejected the text as not a Discord ID/username: a clean "no mapping".
            return None, not error.startswith("HTTP 400")
        players = data.get("players")
        if not isinstance(players, list):
            self.logger.warning("Fragdex returned an invalid Discord name lookup response.")
            return None, True
        ids = {
            p["discord_id"] for p in players
            if isinstance(p, dict) and isinstance(p.get("discord_id"), str) and p["discord_id"]
        }
        if len(ids) == 1:
            return next(iter(ids)), False
        if len(ids) > 1:
            self.logger.warning("Fragdex returned multiple Discord accounts matching %s.", discord_name)
        else:
            self.logger.warning("Fragdex has no mapping for Discord name %s.", discord_name)
        return None, False

    def _resolve_steam_persona_name(self, steam_id):
        sid = str(steam_id)
        if not sid.isascii() or not sid.isdecimal():
            self.logger.warning("Failed to resolve Steam persona: invalid Steam ID %r.", steam_id)
            return None

        data, error = self._fragdex_api_request("/players/lookup", {"steam_ids": [sid]})
        if error:
            self.logger.warning("Fragdex Steam persona lookup failed for Steam ID %s: %s.", sid, error)
            return None

        players = data.get("players")
        if isinstance(players, list):
            player = next(
                (p for p in players if isinstance(p, dict) and p.get("steam_id") == sid),
                None,
            )
            if player is not None and player.get("known") is True:
                steam = player.get("steam")
                persona_name = steam.get("persona") if isinstance(steam, dict) else None
                if isinstance(persona_name, str):
                    clean_name = self.clean_text(persona_name).strip()
                    if clean_name:
                        return clean_name

        self.logger.warning("Fragdex returned no Steam persona for Steam ID %s.", sid)
        return None

    # ---------- Fragdex HTTP ----------
    def _fragdex_config_error(self):
        api_url = str(self.get_cvar("qlx_fragdexUrl") or "").strip().rstrip("/")
        try:
            parsed_url = urlsplit(api_url)
        except ValueError:
            return "invalid qlx_fragdexUrl"
        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
            or parsed_url.query
            or parsed_url.fragment
        ):
            return "qlx_fragdexUrl must be an http:// or https:// URL"
        if not str(self.get_cvar("qlx_fragdexKey") or "").strip():
            return "qlx_fragdexKey is not configured"
        return None

    def _fragdex_api_request(self, path, body=None):
        """Returns (payload_dict, None) or (None, error_string). Never raises."""
        config_error = self._fragdex_config_error()
        if config_error:
            return None, config_error

        api_url = str(self.get_cvar("qlx_fragdexUrl") or "").strip().rstrip("/")
        api_key = str(self.get_cvar("qlx_fragdexKey") or "").strip()
        try:
            request_body = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Authorization": "Bearer {}".format(api_key), "Accept": "application/json"}
            if request_body is not None:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                url=_build_api_url(api_url, path), data=request_body, headers=headers,
                method="POST" if request_body is not None else "GET",
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return None, "response was too large"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return None, "invalid JSON response"
            return payload, None
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            suffix = " (retry after {}s)".format(retry_after) if retry_after else ""
            return None, "HTTP {}{}".format(error.code, suffix)
        except urllib.error.URLError as error:
            return None, "network error: {}".format(error.reason)
        except (http.client.HTTPException, OSError, ValueError) as error:
            return None, "request failed: {}".format(error)
