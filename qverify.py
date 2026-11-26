# SPDX-License-Identifier: GPL-3.0-or-later
"""qverify: check that the players on Red and Blue are the players of the active FragQ PUG, and fix it.

One file for both minqlx and minqlxtended. Works on its own: it doesn't need the fragq or fragdex plugins to
be loaded, only their settings.

    !queueverify        compare the FragQ match with the teams and fix the differences (qlx_qverifyAdminLevel)
    !queueverify dry    only report what would change
    !queueverify status the FragQ key's queues and permissions, like !fragq test
    !qv                 alias of !queueverify, with the same arguments
    !sub <id>       the player in client slot <id> is subbing in the current PUG: !queueverify never moves them and
                    switches the next player who doesn't belong instead; the sub also covers one PUG slot, so the
                    player they replaced isn't added on top of them (qlx_qverifyAdminLevel)
    !sub <id> <id2> the first player subs for the second: they take the second's place in the PUG (and FragQ
                    team), and the second loses it. If the second is still on a team, !queueverify switches the sub
                    into their slot (or moves them to spectator when the sub already plays)
    !unsub <id>     undo !sub: the player loses their protection, and if they were subbing for someone, that
                    player is protected again (also works with the replaced player's id). !sub off <id> is the same
    !sub            list subs; !sub off <id> removes one, !sub clear all. Subs clear when !queueverify finds a new
                    FragQ match.

How it works:
  1. FragQ (POST /api/connect/v1/match, {"queue": qlx_fragqQueue}) lists the queue's matches with each
     player's Discord ID and FragQ team (0, 1, or null while unpicked). The match being played is the newest
     one in state "started" (an unranked match: FragQ hands it to the game as soon as the teams are set) or
     "waiting_report" (a ranked match) with at least half of its players on the server. Matches still in
     check-in or draft aren't being played yet, so they're only mentioned.
  2. Fragdex (POST /api/v1/players/lookup) gives the Discord ID of everyone on the server, in one request.
     A player's FragQ Steam link (from the FragQ answer) is used when Fragdex has no mapping or is down.
  3. The match with the most of its players on the server is the one checked.
  4. On the game thread (@ql.next_frame), with the teams read again and each slot's Steam ID checked:
     - anyone on a team who isn't matched to a PUG player is out of the PUG, with or without a Discord link
       (only while Fragdex is unreachable are unlinked players left alone, as their link couldn't be checked);
     - each PUG spectator is paired with one of them and swapped in by client id with the switch command
       (Player.switch): the PUG player takes that exact slot, so no side has to be known. A PUG spectator
       whose side is known is only swapped with someone on that side;
     - the rest of the players out of the PUG go to spectator; the rest of the PUG spectators are put on their
       side when it's known. FragQ gives teams as 0/1 (Alpha/Beta), not Red/Blue, so a side is known only
       when every PUG player already on a team agrees (all of team 0 on one colour, all of team 1 on the other);
     - otherwise (teams not picked in FragQ, nobody placed yet, or the PUG mixed across colours) they're told
       to join, in chat and on screen. A side is never guessed: a player on the wrong team is worse.
     1.5 s later the moves are checked, since a queue or balance plugin can undo a switch, and the summary
     goes to whoever ran the command, with anything that failed or was undone.
  Players without a Discord mapping are never moved (they can't be checked), only listed. If FragQ or
  Fragdex can't be reached, nothing is moved.

Settings read (not defined) here, with the same precedence as fragq.py / fragdex.py: the URL and key saved
in the bot database (minqlx:fragq:url / :key, minqlx:fragdex:url / :key) win over the cvars
qlx_fragqUrl / qlx_fragqKey / qlx_fragdexUrl / qlx_fragdexKey. Also qlx_fragqQueue, qlx_fragqVerifyTls and
qlx_fragdexVerifyTls.

Cvars:
    qlx_qverifyAdminLevel   permission level for !queueverify (default 3)

The FragQ connector key needs the "Check linked players" permission.
"""
import collections
import json
import re
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

try:
    import minqlxtended as ql
    STOP_ALL = ql.Return.STOP_ALL
    RUNTIME = "minqlxtended"
except ImportError:
    import minqlx as ql
    STOP_ALL = ql.RET_STOP_ALL
    RUNTIME = "minqlx"

VERSION = "1.0.0"
FRAGQ_DB_URL = "minqlx:fragq:url"
FRAGQ_DB_KEY = "minqlx:fragq:key"
FRAGDEX_DB_URL = "minqlx:fragdex:url"
FRAGDEX_DB_KEY = "minqlx:fragdex:key"
TIMEOUT = 10              # seconds per HTTP request
FRAGDEX_BATCH = 100       # Steam IDs per Fragdex lookup (server limit)
MAX_JOBS = 4
CONFIRM_DELAY = 1.5       # seconds after the moves to check they stuck (queue.py reacts after 0.5 s)
PLAYING_STATES = {"started", "waiting_report"}   # teams set and the game on: what the server should match
PRE_GAME_STATES = {"init", "check_in", "draft"}   # still in Discord
TAG = "^1QVerify:^7"
COLOR_RE = re.compile(r"\^[0-9]")


# ---------------------------------------------------------------- helpers (copied from fragq.py)

def _is_steam_id(sid):
    s = str(sid)
    return len(s) == 17 and s.isdigit() and s.startswith("7656119")


def _api_url(url):
    """'fragq.example.com', 'https://host:4443' or the full .../api/connect/v1 URL -> the API base URL, or None."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    path = re.sub(r"/api(/.*)?\Z", "", parts.path.rstrip("/"), flags=re.IGNORECASE)
    return f"{parts.scheme}://{parts.netloc}{path}/api/connect/v1"


def _fragdex_api_url(url):
    """Same as fragdex.py's _api_url: the base URL with /api/v1, or None."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        return None
    return url if url.endswith("/api/v1") else url + "/api/v1"


def _text(s):
    """Safe for tell(): the QL client reads % as a format code and corrupts its state."""
    return str(s).replace("%", "％")


def _clean(s):
    return COLOR_RE.sub("", str(s or ""))


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team(team):
    """'red', 'blue', 'free', 'spectator': minqlx gives strings, minqlxtended Team members."""
    return str(getattr(team, "name", team) or "").lower()


def _with_queue(payload, cfg):
    """The request with qlx_fragqQueue added, unless it already names a queue."""
    if cfg.get("queue") and not payload.get("queue"):
        return dict(payload, queue=cfg["queue"])
    return payload


def _request(base, key, verify_tls, method, path, body=None, user_agent="qverify"):
    """Returns (data, error, status). Never raises. The same shape as fragq.py's _request."""
    if not base or not key:
        return None, "address or key not set", 0
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": f"{user_agent}-{RUNTIME}/{VERSION}"})
    ctx = None if verify_tls else ssl._create_unverified_context()  # noqa: S323 - opt-in
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            payload, status = json.loads(resp.read().decode("utf-8")), resp.status
        if not isinstance(payload, dict):
            return None, "invalid JSON answer", status
        return payload, None, status
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error") or e.reason
        except Exception:  # noqa: BLE001 - not a JSON reply (proxy page etc.)
            msg = e.reason
        return None, f"HTTP {e.code}: {msg}", e.code
    except Exception as e:  # noqa: BLE001 - network errors, bad JSON, TLS
        return None, str(getattr(e, "reason", e))[:200], 0


# ---------------------------------------------------------------- the decision (pure, tested on its own)

def plan(roster, on_server, discord_of, lookup_ok=True, protected=()):
    """
    roster:     {discord_id: fragq team 0 / 1 / None} of the FragQ match
    on_server:  [(client_id, steam_id, name, team)] with team 'red' / 'blue' / 'spectator' / ...
    discord_of: {steam_id: discord_id} for the players that could be resolved
    lookup_ok:  False when Fragdex couldn't be asked: then a missing mapping proves nothing
    protected:  subs (!sub), {sub Steam ID: replaced Steam ID or None} (a plain list of Steam IDs is fine too).
                - A sub for a named player (!sub <sub> <replaced>) takes that player's place in the PUG, with
                  their FragQ team: protected on a team, brought in from spectator (into the replaced player's
                  slot first), while the replaced player is out of the PUG, linked or not.
                - A sub without one (!sub <sub>) is never moved, and on a team covers one PUG slot.

    Returns a dict:
      switch      [(out_entry, in_entry)]: a player on a team who isn't in the PUG and a PUG spectator who takes
                  their slot, with the switch command (no side needs to be known)
      evict       entries on a team who aren't in the PUG and have no PUG spectator to swap with: to spectator
      place       [(entry, 'red'|'blue')]: PUG spectators whose side is known and who had nobody on that side
                  to swap with, to put there directly
      wait        [(entry, reason)]: PUG spectators with nobody to swap with and no known side: prompted
      unverified  entries on a team without a mapping while Fragdex was down (left alone)
      subs        entries of protected subs on a team (left alone)
      covered     PUG spectators not brought in because a sub has their slot: those who'd have been put or
                  prompted (a switch replaces a non-PUG player, so it never needs the slot), one per sub, on
                  the sub's side when it's known
      missing     Discord IDs of the PUG not on the server
      sides       {0: 'red'|'blue', 1: ...} or None, and sides_why when None

    Anyone on a team who isn't matched to a PUG player is out of the PUG, linked or not: the PUG is the
    FragQ roster, and an unlinked player can't be on it. Only when Fragdex was unreachable are unlinked
    players left alone, as their link couldn't be checked.

    FragQ gives each player's team as 0/1 (Alpha/Beta), not Red/Blue: captains pick sides in the game. A side is
    known only when the PUG players already on teams agree: every one of them on team 0 on one colour and every
    one on team 1 on the other. Anything mixed, or nobody placed yet, isn't guessed; a switch doesn't need it.
    """
    evict, pull, unverified, subs, present = [], [], [], [], set()
    protected = dict(protected) if isinstance(protected, dict) else dict.fromkeys(protected)
    replaced = {rep: sub for sub, rep in protected.items() if rep}   # replaced Steam ID -> their sub
    member_fq = {}   # Steam ID -> FragQ team of everyone on the server who holds a PUG place
    for entry in on_server:
        _, sid, _, team = entry
        did = discord_of.get(sid)
        playing = team in ("red", "blue")
        if sid in replaced and sid not in protected:     # subbed out: their place went to the sub
            if did in roster:
                present.add(did)
            if playing:
                evict.append(entry)
            continue
        if protected.get(sid):                           # subbed in for a named player: holds their place
            rdid = discord_of.get(protected[sid])
            if rdid in roster:
                present.add(rdid)
            member_fq[sid] = roster.get(rdid)
            if not playing:
                pull.append(entry)
            continue
        if sid in protected and did not in roster:
            if playing:
                subs.append(entry)
            continue
        if did is None:
            if playing:
                (evict if lookup_ok else unverified).append(entry)
            continue
        if did in roster:
            present.add(did)
            member_fq[sid] = roster[did]
            if not playing:
                pull.append(entry)
        elif playing:
            evict.append(entry)

    # FragQ's team 0/1 -> Red/Blue, only from unanimous evidence.
    count = collections.Counter()
    for _, sid, _, team in on_server:
        fq = member_fq.get(sid)
        if fq in (0, 1) and team in ("red", "blue"):
            count[(fq, team)] += 1
    straight = count[(0, "red")] + count[(1, "blue")]
    crossed = count[(0, "blue")] + count[(1, "red")]
    sides, sides_why = None, None
    if straight and not crossed:
        sides = {0: "red", 1: "blue"}
    elif crossed and not straight:
        sides = {0: "blue", 1: "red"}
    elif straight and crossed:
        sides_why = "the PUG's teams are mixed across Red and Blue"
    else:
        sides_why = "no PUG player is on a team yet"

    # Pair each PUG spectator with a player to remove. One whose side is known only takes a slot on that side.
    # A sub for a named player takes exactly that player's slot when they're still on a team.
    out_left, switch, place, wait, unpaired = list(evict), [], [], [], []
    for entry in list(pull):
        partner = next((e for e in out_left if e[1] == protected.get(entry[1])), None)
        if partner is not None:
            out_left.remove(partner)
            pull.remove(entry)
            switch.append((partner, entry))
    for entry in pull:
        fq = member_fq.get(entry[1])
        side = sides[fq] if sides is not None and fq in (0, 1) else None
        if side is not None:
            partner = next((e for e in out_left if e[3] == side), None)
            if partner is not None:
                out_left.remove(partner)
                switch.append((partner, entry))
            else:
                place.append((entry, side))
        else:
            unpaired.append((entry, fq))
    for entry, fq in unpaired:
        if out_left:
            switch.append((out_left.pop(0), entry))
        elif fq not in (0, 1):
            wait.append((entry, "teams not picked in FragQ"))
        else:
            wait.append((entry, sides_why))

    # A sub on a team fills the slot of the PUG player they replaced: don't add that player on top of them.
    covered = []
    for sub in subs:
        hit = next((x for x in place if x[1] == sub[3]), None)
        if hit is not None:
            place.remove(hit)
            covered.append(hit[0])
        elif wait:
            covered.append(wait.pop(0)[0])
    return dict(switch=switch, evict=out_left, place=place, wait=wait, unverified=unverified, subs=subs,
                covered=covered, sides=sides, sides_why=sides_why, member_fq=member_fq,
                missing=[did for did in roster if did not in present])


class qverify(ql.Plugin):
    def __init__(self):
        super().__init__()
        self.set_cvar_once("qlx_qverifyAdminLevel", "3")

        self._lock = threading.Lock()
        self._jobs = collections.deque(maxlen=MAX_JOBS)
        self._busy = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        # !sub: Steam ID -> (name, replaced Steam ID or None, replaced name or None) of approved subs (game thread
        # only), for the FragQ match in _subs_match. Cleared when !queueverify finds a different match.
        self._subs = {}
        self._subs_match = None

        self.add_hook("unload", self.handle_unload)
        self.add_command(("queueverify", "qv"), self.cmd_queueverify, usage="[dry|status]")
        self.add_command("sub", self.cmd_sub, usage="<client_id> [<client_id>] | off <client_id> | clear")
        self.add_command("unsub", self.cmd_unsub, usage="<client_id>")

        self._thread = threading.Thread(target=self._worker, name="qverify", daemon=True)
        self._thread.start()

    def handle_unload(self, plugin):
        if plugin == self.__class__.__name__:
            self._stop.set()
            self._wake.set()

    # ------------------------------------------------------------ config (game thread)

    def _db_get(self, key):
        try:
            return self.db.get(key)
        except Exception:  # noqa: BLE001 - no database configured: cvars only
            return None

    def load_config(self):
        """The same precedence as fragq.py / fragdex.py: database values first, then the cvars."""
        return {
            "fragq_url": _api_url(self._db_get(FRAGQ_DB_URL) or self.get_cvar("qlx_fragqUrl")) or "",
            "fragq_key": (self._db_get(FRAGQ_DB_KEY) or self.get_cvar("qlx_fragqKey") or "").strip(),
            "fragq_tls": _int(self.get_cvar("qlx_fragqVerifyTls"), 1) != 0,
            "queue": " ".join(_clean(self.get_cvar("qlx_fragqQueue")).split())[:60],
            "fragdex_url": _fragdex_api_url(self._db_get(FRAGDEX_DB_URL) or self.get_cvar("qlx_fragdexUrl")) or "",
            "fragdex_key": (self._db_get(FRAGDEX_DB_KEY) or self.get_cvar("qlx_fragdexKey") or "").strip(),
            "fragdex_tls": _int(self.get_cvar("qlx_fragdexVerifyTls"), 1) != 0,
        }

    def _snapshot(self):
        """[(client id, Steam ID, name, team)] of everyone on the server (game thread)."""
        out = []
        for p in self.players():
            sid = str(p.steam_id)
            if _is_steam_id(sid):
                out.append((p.id, sid, _clean(p.name), _team(p.team)))
        return out

    # ------------------------------------------------------------ command

    def _sub_label(self, sid):
        name, _, rep_name = self._subs[sid]
        return f"{name} (for {rep_name})" if rep_name else name

    def _slot(self, arg):
        """The player in client slot `arg`, or None."""
        cid = _int(arg, -1)
        if not 0 <= cid < 64:
            return None
        try:
            p = self.player(cid)
        except Exception:  # noqa: BLE001 - NonexistentPlayerError: empty slot
            return None
        return p if p is not None and _is_steam_id(p.steam_id) else None

    def cmd_sub(self, player, msg, channel):
        """!sub <client_id> [<client_id>]: the first player is subbing in the current PUG.
        - With one id, !queueverify leaves them on their team and switches the next player who doesn't belong
          instead; they also cover one PUG slot.
        - With a second id, they sub for that player: they take that player's place in the PUG (and their FragQ
          team), and the replaced player loses it, so if they're still on a team !queueverify switches the sub in
          for them (or moves them to spectator when the sub already plays).
        !sub lists, !sub off <id> removes, !sub clear removes all. Subs last until !queueverify finds a new match."""
        level = _int(self.get_cvar("qlx_qverifyAdminLevel"), 3)
        if not self.db.has_permission(player, level):
            player.tell(f"{TAG} you need permission level {level} for that.")
            return STOP_ALL
        args = [a.lower() for a in msg[1:]]
        if not args:
            listed = ", ".join(self._sub_label(sid) for sid in self._subs) or "none"
            self._reply_now(player, channel, f"{TAG} subs: {listed}.")
            return STOP_ALL
        if args[0] == "clear":
            self._subs.clear()
            self._reply_now(player, channel, f"{TAG} subs cleared.")
            return STOP_ALL
        remove = args[0] in ("off", "remove", "del")
        if remove and len(args) < 2:
            self._reply_now(player, channel, f"{TAG} usage: !sub <client_id> [<client_id>] | off <client_id> | clear")
            return STOP_ALL
        target_arg = args[1] if remove else args[0]
        target = self._slot(target_arg)
        if target is None:
            self._reply_now(player, channel, f"{TAG} no player with client id {target_arg}.")
            return STOP_ALL
        sid, name = str(target.steam_id), _clean(target.name)
        if remove:
            self._reply_now(player, channel, self._unsub(sid, name))
            return STOP_ALL

        rep_sid = rep_name = None
        if len(args) > 1:
            replaced = self._slot(args[1])
            if replaced is None:
                self._reply_now(player, channel, f"{TAG} no player with client id {args[1]}.")
                return STOP_ALL
            rep_sid, rep_name = str(replaced.steam_id), _clean(replaced.name)
            if rep_sid == sid:
                self._reply_now(player, channel, f"{TAG} a player can't sub for themselves.")
                return STOP_ALL

        # A player who is in the PUG needs no protection: ask FragQ first (worker thread), then add on the game
        # thread in _finish_sub.
        cfg = self.load_config()
        with self._lock:
            if self._busy or self._jobs:
                self._reply_now(player, channel, f"{TAG} a check is already running, try again in a moment.")
                return STOP_ALL
            self._jobs.append((self._reply_target(player, channel), cfg, self._snapshot(), "sub",
                               [(sid, name, target.id, rep_sid, rep_name)]))
        self._wake.set()
        self._reply_now(player, channel, f"{TAG} checking whether {name} is already in the PUG...")
        return STOP_ALL

    @ql.next_frame
    def _finish_sub(self, reply_to, request, found):
        """Add the sub unless FragQ says they're already in the PUG (game thread)."""
        sid, name, client_id, rep_sid, rep_name = request
        if isinstance(found, str):   # couldn't check: add anyway, extra protection does no harm
            self._add_sub(reply_to, request, f" (couldn't check the PUG: {found})")
            return
        roster, discord_of, info = found
        if discord_of.get(sid) in roster:
            self.logger.info("qverify: %s (%s) is in FragQ match %s; not added as a sub.", name, sid, info["match_id"])
            why = (f"; to take {rep_name}'s place they'd have to leave it" if rep_sid else
                   ": !queueverify already keeps them on their team")
            self._reply_lines(reply_to, [f"{TAG} {name} is in the PUG (FragQ match #{info['match_id']}), so they "
                                         f"don't need sub protection{why}."])
            return
        self._add_sub(reply_to, request, "")

    def _add_sub(self, reply_to, request, note):
        sid, name, client_id, rep_sid, rep_name = request
        if rep_sid:
            # The replaced player gives up their place: they're no longer a sub themselves, and nobody else
            # subs for them any more.
            self._subs.pop(rep_sid, None)
            for other, (_, other_rep, _) in list(self._subs.items()):
                if other_rep == rep_sid and other != sid:
                    del self._subs[other]
        self._subs[sid] = (name, rep_sid, rep_name)
        if rep_sid:
            self.logger.info("qverify: %s (%s) subs for %s (%s).", name, sid, rep_name, rep_sid)
            line = (f"{TAG} {name} subs for {rep_name}: !queueverify keeps {name} in the PUG and takes {rep_name} out "
                    f"(switching {name} into their slot if they're still on a team){note}.")
        else:
            self.logger.info("qverify: %s (%s) marked as a sub.", name, sid)
            line = (f"{TAG} {name} is a sub: !queueverify won't move them, and switches the next player who doesn't "
                    f"belong instead{note}.")
        self._reply_lines(reply_to, [line])
        target = self._player((client_id, sid))
        if target is not None and not (reply_to[0] == "player" and reply_to[1] == client_id):
            target.tell(_text(f"{TAG} you're subbing in this PUG" + (f" for {rep_name}" if rep_name else "") +
                              ": you won't be moved off your team."))

    def _unsub(self, sid, name):
        """Undo a sub (game thread). Returns the reply. `sid` is the sub, or the player someone subs for. The
        sub loses their protection; the player they subbed for gets it back, as a plain sub so they aren't moved
        even without a Discord link (a linked PUG player has their PUG place back anyway)."""
        if sid not in self._subs:
            sid = next((s for s, (_, rep, _) in self._subs.items() if rep == sid), None)
            if sid is None:
                return f"{TAG} {name} isn't a sub, and nobody subs for them."
        sub_name, rep_sid, rep_name = self._subs.pop(sid)
        if rep_sid is None:
            self.logger.info("qverify: %s (%s) is no longer a sub.", sub_name, sid)
            return f"{TAG} {sub_name} is no longer a sub: !queueverify can move them again."
        self._subs[rep_sid] = (rep_name, None, None)
        self.logger.info("qverify: %s (%s) no longer subs for %s (%s); %s is protected again.",
                         sub_name, sid, rep_name, rep_sid, rep_name)
        for steam_id, line in ((sid, f"{TAG} you're no longer subbing in this PUG."),
                               (rep_sid, f"{TAG} you're back in this PUG: you won't be moved off your team.")):
            p = next((x for x in self.players() if str(x.steam_id) == steam_id), None)
            if p is not None:
                p.tell(_text(line))
        return (f"{TAG} {sub_name} no longer subs for {rep_name}: {rep_name} is protected again, and "
                f"!queueverify can move {sub_name}.")

    def cmd_unsub(self, player, msg, channel):
        """!unsub <client_id>: undo !sub for that player (or for whoever subs for them)."""
        level = _int(self.get_cvar("qlx_qverifyAdminLevel"), 3)
        if not self.db.has_permission(player, level):
            player.tell(f"{TAG} you need permission level {level} for that.")
            return STOP_ALL
        if len(msg) < 2:
            self._reply_now(player, channel, f"{TAG} usage: !unsub <client_id>")
            return STOP_ALL
        target = self._slot(msg[1])
        if target is None:
            self._reply_now(player, channel, f"{TAG} no player with client id {msg[1]}.")
            return STOP_ALL
        self._reply_now(player, channel, self._unsub(str(target.steam_id), _clean(target.name)))
        return STOP_ALL

    def cmd_queueverify(self, player, msg, channel):
        level = _int(self.get_cvar("qlx_qverifyAdminLevel"), 3)
        if not self.db.has_permission(player, level):
            player.tell(f"{TAG} you need permission level {level} for that.")
            return STOP_ALL
        sub = msg[1].lower() if len(msg) > 1 else ""
        mode = "status" if sub == "status" else "dry" if sub in ("dry", "check", "test") else "fix"
        cfg = self.load_config()
        if not cfg["fragq_url"] or not cfg["fragq_key"]:
            self._reply_now(player, channel, f"{TAG} FragQ address or key not set (qlx_fragqUrl / qlx_fragqKey).")
            return STOP_ALL
        players = self._snapshot()
        if not players and mode != "status":
            self._reply_now(player, channel, f"{TAG} nobody to check.")
            return STOP_ALL
        with self._lock:
            if self._busy or self._jobs:
                self._reply_now(player, channel, f"{TAG} a check is already running, try again in a moment.")
                return STOP_ALL
            # Replaced players are looked up too, so a sub keeps their FragQ team after they disconnect.
            replaced = [rep for _, rep, _ in self._subs.values() if rep]
            self._jobs.append((self._reply_target(player, channel), cfg, players, mode, replaced))
        self._wake.set()
        if mode == "status":
            self._reply_now(player, channel, f"{TAG} asking FragQ...")
        else:
            self._reply_now(player, channel, f"{TAG} checking the teams against FragQ" +
                            (f" (queue {cfg['queue']})..." if cfg["queue"] else "..."))
        return STOP_ALL

    @staticmethod
    def _reply_target(player, channel):
        """Something a worker thread can reply to safely later: the console channel, or a player's
        client id + Steam ID so the reply can't reach whoever takes over the slot after they leave."""
        if getattr(channel, "name", "") == "console":
            return ("console", channel)
        return ("player", player.id, str(player.steam_id))

    @staticmethod
    def _reply_now(player, channel, line):
        if getattr(channel, "name", "") == "console":
            channel.reply(_text(line))
        else:
            player.tell(_text(line))

    # ------------------------------------------------------------ worker thread: HTTP only

    def _worker(self):
        while not self._stop.is_set():
            self._wake.wait(5)
            self._wake.clear()
            while not self._stop.is_set():
                with self._lock:
                    if not self._jobs:
                        break
                    job = self._jobs.popleft()
                    self._busy = True
                try:
                    self._run(*job)
                except Exception:  # noqa: BLE001 - keep the worker alive whatever a reply contains
                    self.logger.exception("qverify: check failed")
                    self._reply(job[0], f"{TAG} the check failed unexpectedly; see the server log.")
                finally:
                    with self._lock:
                        self._busy = False

    def _fragq(self, cfg, method, path, body=None):
        return _request(cfg["fragq_url"], cfg["fragq_key"], cfg["fragq_tls"], method, path, body,
                        user_agent="qverify-fragq")

    def _fragq_status(self, cfg):
        """(queue names, {capability: bool}) from GET /status, or (None, error)."""
        data, error, _ = self._fragq(cfg, "GET", "/status")
        if error:
            return None, error
        c = data.get("connector") if isinstance(data.get("connector"), dict) else {}
        return [str(q) for q in c.get("queues") or []], (c.get("can") if isinstance(c.get("can"), dict) else {})

    def _status(self, reply_to, cfg):
        queues, can = self._fragq_status(cfg)
        if queues is None:
            self._reply(reply_to, f"{TAG} couldn't reach FragQ: {can}.")
            return
        allowed = ", ".join(k for k, v in sorted(can.items()) if v) or "none"
        wanted = cfg["queue"]
        if wanted:
            match = next((q for q in queues if q.casefold() == wanted.casefold()), None)
            qline = (f"qlx_fragqQueue '{wanted}' is queue '{match}'." if match else
                     f"^1qlx_fragqQueue '{wanted}' isn't one of this key's queues.")
        else:
            qline = "qlx_fragqQueue is empty: every queue of the key is checked."
        self._reply(reply_to, f"{TAG} key queues: {', '.join(queues) or 'none'}. Permissions: {allowed}.",
                    f"{TAG} {qline}" + ("" if can.get("check") else
                                        " ^1!queueverify needs the key's 'Check linked players' permission."))

    def _fragq_failure(self, cfg, error, status):
        """One line that says which of the failure modes this is."""
        queue = cfg["queue"]
        if status == 0:
            return f"couldn't reach FragQ: {error}"
        if status == 401:
            return f"FragQ refused the key ({error}); check qlx_fragqKey"
        if status == 404:
            return "this FragQ has no POST /match yet; update FragQ"
        if status == 403:
            queues, can = self._fragq_status(cfg)
            if queues is not None and not can.get("check"):
                where = f"reports queue {queue}" if queue and any(q.casefold() == queue.casefold() for q in queues) \
                    else "knows the key"
                return (f"FragQ {where} but the key can't read live state: give it the 'Check linked players' "
                        "permission")
            return f"FragQ refused the request ({error})"
        if status == 400 and queue:
            queues, _ = self._fragq_status(cfg)
            if queues is not None and not any(q.casefold() == queue.casefold() for q in queues):
                return f"FragQ has no queue named {queue}; available queues: {', '.join(queues) or 'none'}"
        return f"FragQ answered {error}"

    def _run(self, reply_to, cfg, players, mode, extra=()):
        if mode == "status":
            self._status(reply_to, cfg)
            return
        if mode == "sub":
            found = self._lookup(cfg, players, [sid for sid in (extra[0][0], extra[0][3]) if sid])
            self._finish_sub(reply_to, extra[0], found)
            return
        found = self._lookup(cfg, players, extra)
        if isinstance(found, str):
            self._reply(reply_to, f"{TAG} {found} Nothing was changed.")
            return
        roster, discord_of, info = found
        self._apply(reply_to, roster, discord_of, info, mode == "dry")

    def _lookup(self, cfg, players, extra_ids=()):
        """The FragQ match this server is playing and everyone's Discord ID (worker thread): (roster {discord_id:
        team}, discord_of {steam_id: discord_id}, info), or a sentence saying why not. `extra_ids` are Steam IDs
        not on the server to look up too (players someone subs for)."""
        data, error, status = self._fragq(cfg, "POST", "/match", _with_queue({}, cfg))
        if error:
            self.logger.warning("qverify: FragQ match lookup failed: %s", error)
            return f"{self._fragq_failure(cfg, error, status)}."
        where = f" for queue {cfg['queue']}" if cfg["queue"] else ""
        matches = [m for m in data.get("matches") or [] if isinstance(m, dict)]
        playing = [m for m in matches if m.get("state") in PLAYING_STATES]
        if not playing:
            pre = [m for m in matches if m.get("state") in PRE_GAME_STATES]
            if pre:
                return (f"FragQ match #{pre[0].get('match_id')}{where} is still in "
                        f"{str(pre[0].get('state')).replace('_', '-')}, so there's nothing to check yet.")
            return f"no active FragQ match{where}."

        discord_of, fragdex_error = self._fragdex_discord_ids(cfg, [sid for _, sid, _, _ in players] + list(extra_ids))
        # FragQ's own Steam links fill the gaps Fragdex leaves (or everything, if Fragdex is down).
        for m in playing:
            for p in m.get("players") or []:
                if isinstance(p, dict) and _is_steam_id(p.get("steam_id")) and str(p.get("discord_id", "")).isdigit():
                    discord_of.setdefault(str(p["steam_id"]), str(p["discord_id"]))
        if fragdex_error and not discord_of:
            return (f"Fragdex couldn't be asked for Discord IDs ({fragdex_error}) and FragQ has no Steam links "
                    "for these players.")

        # Like FragQ's own result matching: at least half of the match's players here, then the newest.
        on_server = {discord_of[sid] for _, sid, _, _ in players if sid in discord_of}

        def overlap(m):
            ids = [str(p.get("discord_id")) for p in m.get("players") or [] if isinstance(p, dict)]
            return sum(i in on_server for i in ids), len(ids)

        candidates = [m for m in playing if overlap(m)[0] >= max(1, -(-overlap(m)[1] // 2))]
        if not candidates:
            newest = playing[0]
            here, total = overlap(newest)
            return (f"the newest FragQ match{where} (#{newest.get('match_id')}) has only {here} of its {total} "
                    "players on this server, so it isn't this game.")
        match = max(candidates, key=lambda m: _int(m.get("started_at"), 0))
        roster, names = {}, {}
        for p in match.get("players") or []:
            if isinstance(p, dict) and str(p.get("discord_id", "")).isdigit():
                did = str(p["discord_id"])
                roster[did] = p.get("team") if p.get("team") in (0, 1) else None
                names[did] = _clean(p.get("discord_name") or did)
        if not roster:
            return f"FragQ match #{match.get('match_id')} has no players."
        info = dict(match_id=match.get("match_id"), queue=_clean(match.get("queue")), names=names,
                    team_names=match.get("team_names") or ["team 1", "team 2"], fragdex_error=fragdex_error)
        return roster, discord_of, info

    def _fragdex_discord_ids(self, cfg, steam_ids):
        """{steam_id: discord_id} from Fragdex, and an error (None when every batch was answered)."""
        if not cfg["fragdex_url"] or not cfg["fragdex_key"]:
            return {}, "qlx_fragdexUrl / qlx_fragdexKey not set"
        out, error = {}, None
        ids = list(dict.fromkeys(steam_ids))
        for i in range(0, len(ids), FRAGDEX_BATCH):
            data, err, _ = _request(cfg["fragdex_url"], cfg["fragdex_key"], cfg["fragdex_tls"], "POST",
                                 "/players/lookup", {"steam_ids": ids[i:i + FRAGDEX_BATCH]}, user_agent="qverify-fragdex")
            if err:
                self.logger.warning("qverify: Fragdex lookup failed: %s", err)
                error = err
                continue
            for p in data.get("players") or []:
                if isinstance(p, dict) and p.get("known") and str(p.get("discord_id") or "").isdigit():
                    out[str(p.get("steam_id"))] = str(p["discord_id"])
        return out, error

    # ------------------------------------------------------------ back on the game thread

    @ql.next_frame
    def _apply(self, reply_to, roster, discord_of, info, dry):
        # Read the teams again: players may have joined, left or switched while FragQ and Fragdex answered.
        lines = [f"{TAG} FragQ match #{info['match_id']} ({info['queue']}), {len(roster)} players."]
        if self._subs_match != info["match_id"]:   # subs belong to one PUG
            if self._subs and self._subs_match is not None:
                lines.append(f"{TAG} new FragQ match: subs cleared ({', '.join(self._sub_label(x) for x in self._subs)}).")
                self._subs.clear()
            self._subs_match = info["match_id"]
        result = plan(roster, self._snapshot(), discord_of, lookup_ok=not info["fragdex_error"],
                      protected={sid: rep for sid, (_, rep, _) in self._subs.items()})
        names = info["names"]
        if info["fragdex_error"]:
            lines.append(f"{TAG} ^3Fragdex: {info['fragdex_error']}; using FragQ's Steam links only, and players "
                         "without one are left alone.")

        switch, evict, place, wait = result["switch"], result["evict"], result["place"], result["wait"]
        if not switch and not evict and not place and not wait:
            lines.append(f"{TAG} ^2the roster is clean: the teams match the PUG.")
        if result["subs"]:
            lines.append(f"{TAG} subs kept on their team: " + ", ".join(e[2] for e in result["subs"]))
        named = [self._sub_label(sid) for sid in self._subs if self._subs[sid][1]]
        if named:
            lines.append(f"{TAG} subbing in: " + ", ".join(named))
        if result["covered"]:
            lines.append(f"{TAG} not brought in, a sub has their slot: " + ", ".join(e[2] for e in result["covered"]))
        if result["unverified"]:
            lines.append(f"{TAG} ^3not checked (Fragdex down, no FragQ link), left alone: " +
                         ", ".join(name for _, _, name, _ in result["unverified"]))
        if result["missing"]:
            lines.append(f"{TAG} PUG players not on the server: " + ", ".join(names[d] for d in result["missing"]))
        if dry:
            if switch:
                lines.append(f"{TAG} would switch: " + ", ".join(f"{i[2]} in for {o[2]} ({o[3]})" for o, i in switch))
            if evict:
                lines.append(f"{TAG} would move to spectator: " + ", ".join(n for _, _, n, _ in evict))
            if place:
                lines.append(f"{TAG} would put on their team: " + ", ".join(f"{e[2]} -> {s}" for e, s in place))
            if wait:
                lines.append(f"{TAG} would ask to join ({wait[0][1]}): " + ", ".join(e[2] for e, _ in wait))
            self._reply_lines(reply_to, lines)
            return

        moves, failed = [], []
        switched = []
        for out_entry, in_entry in switch:
            team = out_entry[3]
            error = self._switch(out_entry, in_entry)
            if error is None:
                moves += [(out_entry, "spectator"), (in_entry, team)]
                switched.append(f"{in_entry[2]} in for {out_entry[2]} ({team})")
                self._tell(out_entry, f"{TAG} you're not in the current FragQ PUG, so you were moved to spectator.")
                self._tell(in_entry, f"{TAG} you're in the FragQ PUG: you were put on {team.capitalize()}.",
                           center=True)
            else:
                failed.append(f"{in_entry[2]} <-> {out_entry[2]} ({error})")
        # Evict the rest before putting anyone in, so a team never holds more than its players.
        for entry in evict:
            error = self._put(entry, "spectator")
            if error is None:
                moves.append((entry, "spectator"))
                self._tell(entry, f"{TAG} you're not in the current FragQ PUG, so you were moved to spectator.")
            elif error != "left":
                failed.append(f"{entry[2]} ({error})")
        for entry, side in place:
            error = self._put(entry, side)
            if error is None:
                moves.append((entry, side))
                self._tell(entry, f"{TAG} you're in the FragQ PUG: you were put on {side.capitalize()}.", center=True)
            elif error != "left":
                failed.append(f"{entry[2]} ({error})")
        for entry, _ in wait:
            fq = result["member_fq"].get(entry[1])
            if fq in (0, 1):
                team_name = _clean(info["team_names"][fq])
                mates = [n for _, s, n, t in self._snapshot()
                         if t in ("red", "blue") and result["member_fq"].get(s) == fq]
                hint = f"join your team {team_name}" + (f" (with {', '.join(mates)})" if mates else "")
            else:
                hint = "join a team"
            self._tell(entry, f"{TAG} you're in the FragQ PUG: {hint} now: /team r or /team b.", center=True)

        out_n = sum(1 for _, t in moves if t == "spectator")
        put_in = [f"{e[2]} -> {t}" for e, t in moves[2 * len(switched):] if t != "spectator"]
        lines.append(f"{TAG} pulled {out_n} non-PUG player(s) to spectator." +
                     (f" Switched in {len(switched)} PUG member(s): {', '.join(switched)}." if switched else "") +
                     (f" Put {len(put_in)} PUG member(s) on their team: {', '.join(put_in)}." if put_in else ""))
        if wait:
            lines.append(f"{TAG} {len(wait)} PUG member(s) waiting: {', '.join(e[2] for e, _ in wait)}. They can now "
                         f"join their assigned team ({'; '.join(dict.fromkeys(r for _, r in wait))}).")
        if failed:
            lines.append(f"{TAG} ^1couldn't move: " + ", ".join(failed))
        self.logger.info("qverify: match %s: %d switched, %d to spectator, %d put on a team, %d prompted, %d failed.",
                         info["match_id"], len(switched), out_n, len(put_in), len(wait), len(failed))
        if moves:
            self._confirm(reply_to, moves, lines)   # report once we've seen the moves stick
        else:
            self._reply_lines(reply_to, lines)

    @ql.delay(CONFIRM_DELAY)
    def _confirm(self, reply_to, moves, lines):
        """A put can be undone by another plugin (a queue or balance plugin reacting to the switch): check."""
        undone = []
        for entry, team in moves:
            p = self._player(entry)
            if p is not None and _team(p.team) != team:
                undone.append(f"{entry[2]} (now {_team(p.team)}, wanted {team})")
        if undone:
            self.logger.warning("qverify: moves undone after %.1fs: %s", CONFIRM_DELAY, ", ".join(undone))
            lines = lines + [f"{TAG} ^1moved back by the server or another plugin: " + ", ".join(undone)]
        self._reply_lines(reply_to, lines)

    def _player(self, entry):
        """The player in this slot if it's still the same Steam account, else None."""
        client_id, sid = entry[0], entry[1]
        try:
            p = self.player(client_id)
        except Exception:  # noqa: BLE001 - NonexistentPlayerError: they left
            return None
        return p if p is not None and str(p.steam_id) == sid else None

    def _switch(self, out_entry, in_entry):
        """Swap a player who isn't in the PUG with a PUG spectator by client id (game thread): the switch
        command, Player.switch, puts the first on the second's team (spectator) and the second in the first's
        slot. None when done, else the error. If one of them left, the other half is done with a put."""
        p_out, p_in = self._player(out_entry), self._player(in_entry)
        if p_in is None:
            self.logger.debug("qverify: %s left before the switch; %s only goes to spectator.", in_entry[2], out_entry[2])
            error = self._put(out_entry, "spectator")
            return None if error in (None, "left") else error
        if p_out is None:
            self.logger.debug("qverify: %s left before the switch; %s takes the free slot.", out_entry[2], in_entry[2])
            error = self._put(in_entry, out_entry[3])
            return None if error is None else error
        try:
            p_out.switch(p_in)
            return None
        except Exception as e:  # noqa: BLE001 - e.g. the game rejects it: fall back to the two puts it stands for
            self.logger.warning("qverify: switch %s <-> %s failed (%s); trying put.", out_entry[2], in_entry[2], e)
        error = self._put(out_entry, "spectator") or self._put(in_entry, out_entry[3])
        return None if error is None else error

    def _put(self, entry, team):
        """Move the player in this slot (game thread). None when done, 'left' when the slot changed hands, else
        the error. Like fragq.py's _enforce: the team name first, then minqlxtended's Team member."""
        p = self._player(entry)
        if p is None:
            self.logger.debug("qverify: %s left before the move to %s; skipped.", entry[2], team)
            return "left"
        try:
            p.put(team)
            return None
        except Exception:  # noqa: BLE001 - minqlxtended may want its Team member
            pass
        try:
            p.put(getattr(ql, "Team")[team.upper()])
            return None
        except Exception as e:  # noqa: BLE001 - team full, game state, a bad slot: report, don't stop the others
            self.logger.warning("qverify: couldn't put %s on %s: %s", entry[2], team, e)
            return str(e)[:80] or type(e).__name__

    def _tell(self, entry, line, center=False):
        p = self._player(entry)
        if p is None:
            return
        p.tell(_text(line))
        if center:
            p.center_print(_text(_clean(line.replace(TAG, "").strip())))

    def _reply_lines(self, reply_to, lines):
        if reply_to[0] == "console":
            for line in lines:
                reply_to[1].reply(_text(line))
            return
        target = self._player((reply_to[1], reply_to[2]))
        if target is not None:
            for line in lines:
                target.tell(_text(line))

    @ql.next_frame
    def _reply(self, reply_to, *lines):
        self._reply_lines(reply_to, list(lines))
