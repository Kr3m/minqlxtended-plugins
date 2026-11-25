# This file is part of minqlxtended.
#
# minqlxtended is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""mverify - check that the players on red/blue match a tournament match roster.

The roster comes from the tournament site's match API::

    GET <qlx_mverify_apiUrl>/api/v1/match/<match_id>
    -> {"id": 4, "team1_id": 1, "team2_id": 2,
        "team1_players": ["7656119..."], "team2_players": ["7656119..."]}

Cvars (all read live on every command, so changing one needs no reload):

    qlx_mverify_enable   "1"  Master switch. "0" makes !mverify reply "disabled" and do no HTTP.
    qlx_mverify_apiUrl   ""   Base URL of the site, e.g. "https://kr3m.one". A bare host gets
                              https:// prepended; a trailing slash or a pasted
                              "/api/v1/match" suffix is stripped. Empty = not configured.
    qlx_mverify_timeout  "5"  HTTP timeout in seconds (clamped to 1-30).

Linked-account exception (optional, via fragdex.py's cvars - they are owned by fragdex.py and
only *read* here, never set): if qlx_fragdexUrl / qlx_fragdexKey are configured, a player who
is NOT in the roster but whose SteamID is linked in Fragdex (GET /players/<sid>/linked) to a
rostered SteamID passes verification as that rostered entry. Lookups run in the same worker
thread as the roster fetch, are cached for FRAGDEX_CACHE_TTL seconds so !mverify can be
repeated freely, and if Fragdex is unreachable the command falls back to roster-only results
and says so.

Command:

    !mverify <match_id>   Permission level 2 (admin). It is read-only, but it makes the server
                          issue an outbound HTTP request per call, so it is not left open to
                          every player. <match_id> is a positive integer (<= 4294967295, the
                          range the API accepts).

SteamIDs are compared as strings throughout (trimmed, exact match).
"""

import re
import time
import urllib.parse

import minqlxtended
import requests

MAX_MATCH_ID = 4294967295
API_PATH = "/api/v1/match"
FRAGDEX_CACHE_TTL = 300  # seconds a linked-accounts lookup is reused

try:
    # Reuse fragdex.py's URL normalizer when the plugin is importable.
    from fragdex import _api_url as fragdex_api_url
except Exception:  # noqa: BLE001 - fragdex.py absent or not importable: replicate its logic
    def fragdex_api_url(url):
        """Replica of fragdex.py's _api_url(): host or full URL -> '.../api/v1' base, or None."""
        url = (url or "").strip().rstrip("/")
        if not url:
            return ""
        if "://" not in url:
            url = "https://" + url
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
            return None
        return url if url.endswith("/api/v1") else url + "/api/v1"


def normalize_api_url(raw):
    """Return the base URL without trailing slash / API path, or "" if unset.

    Decision point: normalization. Admins will type "kr3m.one", "https://kr3m.one/" or paste the
    whole endpoint. We accept all of them and rebuild the endpoint ourselves, so the match ID is
    never concatenated onto a user-supplied path. A missing scheme defaults to https because the
    live site is https-only; http:// is still honoured if given explicitly.
    """
    url = (raw or "").strip()
    if not url:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    url = url.rstrip("/")
    if url.endswith(API_PATH):
        url = url[: -len(API_PATH)].rstrip("/")
    return url


def parse_roster(data):
    """Validate the API JSON and return (team1, team2) as lists of stripped SteamID strings.

    Raises ValueError with a human-readable message on any structural problem.
    """
    if not isinstance(data, dict):
        raise ValueError("response is not a JSON object")
    rosters = []
    for key in ("team1_players", "team2_players"):
        if key not in data:
            raise ValueError(f"missing key '{key}'")
        value = data[key]
        if not isinstance(value, list):
            raise ValueError(f"'{key}' is not an array")
        # SteamIDs stay strings. Whitespace is trimmed; nothing else is altered.
        rosters.append([str(sid).strip() for sid in value if str(sid).strip()])
    if not rosters[0] and not rosters[1]:
        raise ValueError("both rosters are empty")
    return rosters[0], rosters[1]


def compare_rosters(team1, team2, live, linked=None):
    """Pure comparison of API rosters against a live snapshot.

    :param team1: SteamID strings of API team1.
    :param team2: SteamID strings of API team2.
    :param live: {"red": [(name, sid)], "blue": [...], "spectator": [...],
                  "skipped": [(name, reason)]} - SteamIDs as strings.
    :param linked: optional {live_sid: rostered_sid} from Fragdex linked accounts; a live
                   player not in the roster but linked to a rostered SteamID counts as that
                   rostered entry (the linked-account exception).
    :returns: summary dict (see the keys built below); contains no game objects.
    """
    roster = {sid: 1 for sid in team1}
    roster.update({sid: 2 for sid in team2 if sid not in roster})
    overlap = set(team1) & set(team2)

    # Linked-account exception: extend the roster so an alt inherits its primary's roster slot.
    alias_of = {}
    for alt, primary in (linked or {}).items():
        if alt not in roster and primary in roster:
            alias_of[alt] = primary
            roster[alt] = roster[primary]

    def wrong_count(mapping):
        # mapping: API roster number -> colour. Count rostered players standing on the other colour.
        n = 0
        for colour in ("red", "blue"):
            for _name, sid in live[colour]:
                r = roster.get(sid)
                if r is not None and mapping[r] != colour:
                    n += 1
        return n

    # Decision point: team1/team2 -> red/blue. The API says nothing about colours, and a
    # tournament match has no fixed "team1 is red" rule. Instead of a cvar that an admin has to
    # remember to flip per match, we pick whichever assignment yields the fewest wrong-team
    # players. Non-roster players are identical under both assignments so they don't influence it.
    a = {1: "red", 2: "blue"}
    b = {1: "blue", 2: "red"}
    wa, wb = wrong_count(a), wrong_count(b)
    if wa <= wb:
        mapping, wrong_n = a, wa
    else:
        mapping, wrong_n = b, wb
    on_teams = sum(1 for c in ("red", "blue") for _n, sid in live[c] if sid in roster)
    if on_teams == 0:
        ambiguity = "no rostered players are on red/blue, so the mapping could not be inferred"
    elif wa == wb:
        ambiguity = f"both assignments give {wa} wrong-team player(s); mapping is a guess"
    else:
        ambiguity = ""
    colour_of = dict(mapping)
    team_of_colour = {c: r for r, c in mapping.items()}

    teams = {}
    linked_ok = []
    for colour in ("red", "blue"):
        expected = team_of_colour[colour]
        t = {"not_in_roster": [], "wrong_team": [], "from": {1: [], 2: []}, "ok": 0}
        for name, sid in live[colour]:
            r = roster.get(sid)
            if r is None:
                t["not_in_roster"].append((name, sid))
                continue
            if sid in alias_of:
                linked_ok.append((name, sid, alias_of[sid]))
            t["from"][r].append((name, sid))
            if r != expected and sid not in overlap:
                t["wrong_team"].append((name, sid, "blue" if colour == "red" else "red", colour))
            else:
                t["ok"] += 1
        t["mixed"] = bool(t["from"][1]) and bool(t["from"][2])
        t["verdict"] = "MISMATCH" if (t["not_in_roster"] or t["wrong_team"] or t["mixed"]) else "OK"
        t["expected_roster"] = expected
        teams[colour] = t

    # Decision point: missing / spectator policy. A rostered player who is spectating IS on the
    # server, so they are reported as an info line ("in roster but spectating"), not as missing.
    # A rostered player who is not connected at all is a warning, but does not by itself turn a
    # team's verdict to MISMATCH: the verdict is about who is on the wrong side, and a late
    # player is normal. Callers that want strictness can check summary["missing"].
    on_server = {sid for c in ("red", "blue", "spectator") for _n, sid in live[c]}
    # A primary whose linked alt is on the server is represented by that alt, not "missing".
    on_server.update(alias_of[sid] for sid in list(on_server) if sid in alias_of)
    spectating = [(n, sid, roster[sid]) for n, sid in live["spectator"] if sid in roster]
    missing = [(sid, roster[sid]) for sid in list(team1) + [s for s in team2 if s not in set(team1)] if sid not in on_server]

    return {
        "mapping": {1: colour_of[1], 2: colour_of[2]},
        "mapping_ambiguity": ambiguity,
        "teams": teams,
        "linked_ok": linked_ok,
        "spectating": spectating,
        "missing": missing,
        "skipped": list(live["skipped"]),
        "overlap": sorted(overlap),
        "wrong_total": wrong_n,
        "ok": all(t["verdict"] == "OK" for t in teams.values()),
    }


def format_summary(match_id, s):
    """Turn a summary dict into (level, text) lines; level is "info" or "warning"."""
    lines = []
    m = s["mapping"]
    lines.append(("info", f"match {match_id}: inferred team1={m[1]}, team2={m[2]}"))
    if s["mapping_ambiguity"]:
        lines.append(("warning", f"mapping ambiguous: {s['mapping_ambiguity']}"))
    if s["overlap"]:
        lines.append(("warning", f"SteamID(s) in BOTH rosters: {', '.join(s['overlap'])}"))
    for colour in ("red", "blue"):
        t = s["teams"][colour]
        lines.append(("info" if t["verdict"] == "OK" else "warning",
                      f"{colour.upper()}: {t['verdict']} (expects team{t['expected_roster']} roster, {t['ok']} correct)"))
        for name, sid in t["not_in_roster"]:
            lines.append(("warning", f"{name} ({sid}) is on {colour} but not in either roster"))
        for name, sid, expected, actual in t["wrong_team"]:
            lines.append(("warning", f"{name} ({sid}) is on the wrong team: expected {expected}, actual {actual}"))
        if t["mixed"]:
            parts = [f"team{r}: " + ", ".join(f"{n} ({sid})" for n, sid in t["from"][r]) for r in (1, 2)]
            lines.append(("warning", f"{colour} has mixed rosters - " + " | ".join(parts)))
    for name, sid, primary in s.get("linked_ok", []):
        lines.append(("info", f"{name} ({sid}) is not in the roster but passes via linked account of rostered {primary}"))
    for name, sid, r in s["spectating"]:
        lines.append(("info", f"{name} ({sid}) is in the team{r} roster but spectating"))
    for sid, r in s["missing"]:
        lines.append(("warning", f"{sid} (team{r} roster) is not on the server"))
    for name, reason in s["skipped"]:
        lines.append(("info", f"skipped {name}: {reason}"))
    lines.append(("info", "RESULT: " + ("all OK" if s["ok"] else "MISMATCH") +
                  f" | wrong-team={s['wrong_total']} missing={len(s['missing'])} spectating={len(s['spectating'])}"))
    return lines


class mverify(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_mverify_enable", "1")
        self.set_cvar_once("qlx_mverify_apiUrl", "")
        self.set_cvar_once("qlx_mverify_timeout", "5")
        self.add_command("mverify", self.cmd_mverify, permission=2, usage="<match_id>")
        # qlx_fragdexUrl / qlx_fragdexKey are deliberately NOT set_cvar_once here: fragdex.py
        # owns their defaults and duplicating them risks a load-order conflict. Read-only.
        self._fdx_cache = {}      # steam_id -> (expires_at, [linked steam_ids]); worker threads only
        self._fdx_warned = set()  # one-time configuration warnings already logged

    # ---- helpers ----------------------------------------------------------------------------

    def fetch_roster(self, base_url, match_id, timeout):
        """Blocking HTTP GET + parse. Only ever called from a worker thread; touches no game state.

        Returns (team1, team2). Raises RuntimeError with a caller-safe message.
        """
        url = f"{base_url}{API_PATH}/{match_id}"
        try:
            res = requests.get(url, timeout=timeout, headers={"Accept": "application/json"})
        except requests.Timeout:
            self.logger.warning("mverify: timeout after %ss for %s", timeout, url)
            raise RuntimeError(f"request timed out after {timeout:g}s") from None
        except requests.ConnectionError as e:
            self.logger.warning("mverify: connection failed for %s: %s", url, e)
            raise RuntimeError("could not connect to the API (connection refused/unreachable)") from None
        except requests.RequestException as e:
            self.logger.warning("mverify: bad request for %s: %s", url, e)
            raise RuntimeError("invalid qlx_mverify_apiUrl") from None

        if res.status_code == 404:
            self.logger.warning("mverify: match %s not found (404)", match_id)
            raise RuntimeError(f"match {match_id} not found")
        if res.status_code != 200:
            self.logger.warning("mverify: HTTP %s from %s", res.status_code, url)
            raise RuntimeError(f"API returned HTTP {res.status_code}")
        try:
            return parse_roster(res.json())
        except ValueError as e:
            self.logger.warning("mverify: bad API payload from %s: %s", url, e)
            raise RuntimeError(f"unusable API response: {e}") from None

    def _fragdex_config(self, timeout):
        """Read fragdex.py's cvars (main thread). Returns {"url", "key", "timeout"} or None when
        the linked-account check must be skipped (unset key / invalid URL). Warns once per reason."""
        key = (self.get_cvar("qlx_fragdexKey", str, "") or "").strip()
        if not key:
            if "key" not in self._fdx_warned:
                self._fdx_warned.add("key")
                self.logger.warning("mverify: qlx_fragdexKey is empty - linked-account checks disabled (roster-only)")
            return None
        url = fragdex_api_url(self.get_cvar("qlx_fragdexUrl", str, ""))
        if not url or not url.startswith(("http://", "https://")):
            if "url" not in self._fdx_warned:
                self._fdx_warned.add("url")
                self.logger.warning("mverify: qlx_fragdexUrl is missing or invalid - linked-account checks disabled")
            return None
        return {"url": url, "key": key, "timeout": timeout}

    def _fetch_linked(self, fdx, sid):
        """Blocking GET of Fragdex linked accounts for one SteamID, cached for FRAGDEX_CACHE_TTL.

        Worker thread only. Returns a list of linked SteamID strings (empty on 404 / none known).
        Raises RuntimeError if Fragdex is unavailable or the reply is unusable.
        """
        now = time.time()
        cached = self._fdx_cache.get(sid)
        if cached and cached[0] > now:
            return cached[1]
        url = f"{fdx['url']}/players/{sid}/linked"
        try:
            res = requests.get(url, timeout=fdx["timeout"],
                               headers={"Authorization": "Bearer " + fdx["key"], "Accept": "application/json"})
        except requests.RequestException as e:
            self.logger.warning("mverify: fragdex request failed for %s: %s", sid, e)
            raise RuntimeError("fragdex unreachable") from None
        if res.status_code == 404:
            linked = []
        elif res.status_code == 200:
            try:
                data = res.json()
                if isinstance(data, dict):
                    data = data.get("linked") or []
                if not isinstance(data, list):
                    raise ValueError("not an array")
                linked = [s for s in (str(a.get("steam_id", "")).strip() for a in data if isinstance(a, dict)) if s]
            except ValueError as e:
                self.logger.warning("mverify: bad fragdex payload from %s: %s", url, e)
                raise RuntimeError("unusable fragdex response") from None
        else:
            self.logger.warning("mverify: fragdex HTTP %s from %s", res.status_code, url)
            raise RuntimeError(f"fragdex HTTP {res.status_code}")
        if len(self._fdx_cache) > 512:
            self._fdx_cache = {k: v for k, v in self._fdx_cache.items() if v[0] > now}
        self._fdx_cache[sid] = (now + FRAGDEX_CACHE_TTL, linked)
        return linked

    def _linked_roster_matches(self, fdx, candidates, roster_sids):
        """Worker thread only. For each candidate SteamID not in the roster, find a Fragdex-linked
        SteamID that IS in the roster. Returns ({candidate: rostered_sid}, unavailable_flag).
        Stops at the first Fragdex failure to keep request volume low."""
        matches = {}
        for sid in candidates:
            try:
                linked = self._fetch_linked(fdx, sid)
            except RuntimeError:
                return matches, True
            for alt in linked:
                if alt in roster_sids:
                    matches[sid] = alt
                    self.logger.info("mverify: %s passes via linked-account exception: linked to rostered %s", sid, alt)
                    break
        return matches, False

    def snapshot_live(self):
        """Capture red/blue/spectator players as (name, sid-string). Main thread only."""
        live = {"red": [], "blue": [], "spectator": [], "skipped": []}
        for p in self.players():
            name = p.clean_name
            if p.is_bot:
                live["skipped"].append((name, "bot"))
                continue
            sid = str(p.steam_id).strip()
            if not sid or sid == "0":
                live["skipped"].append((name, "no SteamID"))
                continue
            team = str(p.team)
            if team in live and team != "skipped":
                live[team].append((name, sid))
        return live

    def verify(self, team1, team2, linked=None):
        """Compare rosters to the current server state and return the summary dict (main thread)."""
        return compare_rosters(team1, team2, self.snapshot_live(), linked)

    def emit(self, channel, match_id, summary):
        for level, text in format_summary(match_id, summary):
            color = "^3" if level == "warning" else "^7"
            channel.reply(f"^6mverify^7: {color}{text}")
            if level == "warning":
                self.logger.warning("mverify: %s", text)
            else:
                self.logger.info("mverify: %s", text)

    # ---- command ----------------------------------------------------------------------------

    def cmd_mverify(self, player, msg, channel):
        if not self.get_cvar("qlx_mverify_enable", bool, True):
            channel.reply("^6mverify^7: disabled (qlx_mverify_enable 0).")
            return

        base_url = normalize_api_url(self.get_cvar("qlx_mverify_apiUrl", str, ""))
        if not base_url:
            channel.reply("^6mverify^7: apiUrl not configured. Set ^3qlx_mverify_apiUrl^7 (e.g. https://kr3m.one).")
            return

        if len(msg) != 2 or not re.fullmatch(r"[0-9]+", msg[1]) or not (1 <= int(msg[1]) <= MAX_MATCH_ID):
            return minqlxtended.RET_USAGE

        match_id = int(msg[1])
        try:
            timeout = min(30.0, max(1.0, self.get_cvar("qlx_mverify_timeout", float, 5.0)))
        except ValueError:
            timeout = 5.0

        channel.reply(f"^6mverify^7: fetching match {match_id}...")
        # Snapshot now (main thread) the red/blue SteamIDs the worker may need to look up in
        # Fragdex; the roster comparison itself still uses a fresh snapshot at reply time.
        snap = self.snapshot_live()
        live_sids = [sid for colour in ("red", "blue") for _name, sid in snap[colour]]
        self.fetch_and_verify(base_url, match_id, timeout, channel,
                              self._fragdex_config(timeout), live_sids)

    # Decision point: async strategy. The hook/command handlers run on the server's main thread,
    # so a blocking requests.get would freeze the game frame for up to the timeout. Precedent in
    # this repo: balance.py does its HTTP in a worker thread and hands results back with
    # @minqlxtended.next_frame. We do the same: @minqlxtended.thread runs ONLY the network call
    # (no game objects are touched there), then next_frame marshals back to the main thread where
    # the live player snapshot is taken (so it reflects the moment of the reply, not the request)
    # and the channel reply is sent. Every failure path is caught and reported the same way.
    # The Fragdex linked-account lookups follow the same pattern (fragdex.py likewise does all
    # its HTTP on worker threads and marshals replies back with next_frame): they run here, in
    # the same worker thread, and only the resulting {sid: rostered_sid} dict crosses back.
    @minqlxtended.thread
    def fetch_and_verify(self, base_url, match_id, timeout, channel, fdx=None, live_sids=None):
        try:
            team1, team2 = self.fetch_roster(base_url, match_id, timeout)
            error = None
        except RuntimeError as e:
            team1 = team2 = None
            error = str(e)
        except Exception:
            self.logger.exception("mverify: unexpected error while fetching")
            team1 = team2 = None
            error = "unexpected error (see server log)"

        linked, fdx_unavailable = {}, False
        if not error and fdx:
            roster_sids = set(team1) | set(team2)
            candidates = [sid for sid in dict.fromkeys(live_sids or []) if sid not in roster_sids]
            try:
                linked, fdx_unavailable = self._linked_roster_matches(fdx, candidates, roster_sids)
            except Exception:
                self.logger.exception("mverify: unexpected error during fragdex lookups")
                fdx_unavailable = True

        @minqlxtended.next_frame
        def finish():
            if error:
                channel.reply(f"^6mverify^7: ^1error^7: {error}")
                return
            if fdx_unavailable:
                channel.reply("^6mverify^7: ^3linked-account check unavailable (Fragdex error); roster-only results.")
            try:
                self.emit(channel, match_id, self.verify(team1, team2, linked))
            except Exception:
                self.logger.exception("mverify: verification failed")
                channel.reply("^6mverify^7: ^1error^7: verification failed (see server log)")

        finish()
