# minqlx - A Quake Live server administrator bot.
# Copyright (C) 2015 Mino <mino@minomino.org>

# This file is part of minqlxtended.

# minqlx is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# minqlx is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with minqlxtended. If not, see <http://www.gnu.org/licenses/>.

# adroundextend — Attack & Defend round extension plugin.
#
# When the last defender is eliminated mid-round (before the round timer
# expires), the round is extended by qlx_adExtendDuration seconds (default 3)
# so the offense has a chance to touch the flag and score.
#
# Mechanism: the dead player is silently respawned underground (below the
# playable area) with no weapons so they are completely invisible and
# unreachable.  The engine sees one defender alive and keeps the round going.
# Every frame the ghost is repositioned underground and healed to 1 HP so it
# cannot be interacted with.  After the extension window expires the ghost is
# removed, which ends the round normally.
#
# The extension is NOT triggered if the round has already ended (e.g. timer
# expired simultaneously with the last death).

import minqlxtended
import time


class adroundextend(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()

        self.add_hook("round_start", self.handle_round_start)
        self.add_hook("death", self.handle_death)
        self.add_hook("frame", self.handle_frame)
        self.add_hook("player_disconnect", self.handle_player_disconnect)

        # round_end and game_end are ZMQ-dependent; register them only when
        # ZMQ stats are available so the plugin still loads without ZMQ.
        try:
            self.add_hook("round_end", self.handle_round_end)
            self.add_hook("game_end", self.handle_game_end)
        except AssertionError:
            self.logger.info(
                "adroundextend: zmq_stats_enable is 0; "
                "round_end/game_end hooks skipped."
            )

        self.set_cvar_once("qlx_adExtendDuration", "3")

        # Per-round runtime state.
        self._round_active = False
        # time.time() when the current extension expires, or None.
        self._extension_end = None
        # client_id of the ghost player keeping the round alive, or None.
        self._ghost_id = None
        self._frame_interval = max(1, (int(self.get_cvar("sv_fps")) + 9) // 10)
        self._frame_counter = 0

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _is_valid_game(self):
        game = self.game
        return (
            game is not None
            and game.state == "in_progress"
            and game.type_short == "ad"
        )

    def _alive_count(self, players):
        """Return the number of alive players from `players`."""
        count = 0
        for p in players:
            state = minqlxtended.player_state(p.id)
            if state and state.is_alive:
                count += 1
        return count

    def _spawn_ghost(self, player):
        """Respawn player underground: no weapons, noclip, 1 HP.

        The ghost is placed far below the map so it is completely invisible
        and unreachable by other players.
        """
        self.logger.info("adroundextend: spawning ghost for %s (id=%s)", player.name, player.id)
        try:
            minqlxtended.player_spawn(player.id)
            # Bury well below the map so no player can see or reach the ghost.
            minqlxtended.set_position(player.id, minqlxtended.Vector3((0, 0, -10000)))
            minqlxtended.noclip(player.id, True)
            minqlxtended.set_health(player.id, 1)
            minqlxtended.set_armor(player.id, 0)
            self._ghost_id = player.id
            self.logger.info("adroundextend: ghost spawned successfully")
        except Exception as e:
            self.logger.warning(
                "adroundextend: failed to spawn ghost for %s: %s", player, e
            )
            self._ghost_id = None

    def _kill_ghost(self):
        """Kill the ghost and disable noclip so the round can end."""
        if self._ghost_id is None:
            return
        try:
            minqlxtended.noclip(self._ghost_id, False)
            minqlxtended.set_health(self._ghost_id, 0)
        except Exception:
            pass
        self._ghost_id = None

    def _reset_extension(self):
        """Clear extension state without killing the ghost."""
        self._ghost_id = None
        self._extension_end = None

    # ------------------------------------------------------------------ #
    #  Event hooks                                                         #
    # ------------------------------------------------------------------ #

    def handle_round_start(self, round_num):
        game = self.game
        self.logger.info(
            "adroundextend: round_start fired round=%s type=%s state=%s",
            round_num, game.type_short if game else None, game.state if game else None
        )
        # Clean up any ghost that survived from the previous round.
        self._kill_ghost()
        self._round_active = True
        self._extension_end = None
        self._ghost_id = None

    def handle_round_end(self, round_number, winning_team, time):
        # Round ended naturally (flag cap or time limit); just clear flags.
        # Don't kill the ghost here — if we triggered the extension it may
        # still be alive, and killing it now could cause a double-end.
        self._round_active = False
        self._reset_extension()

    def handle_game_end(self, aborted):
        self._kill_ghost()
        self._round_active = False
        self._extension_end = None
        self._ghost_id = None

    def handle_player_disconnect(self, player, reason):
        if player.id == self._ghost_id:
            # Ghost disconnected; nothing to kill, just clear the reference.
            self._ghost_id = None

    def handle_death(self, victim, killer, mod):
        """Fires during death processing — before the engine's round-end check.

        If the victim is the last alive player on their team we immediately
        respawn them as an invisible underground ghost to prevent the engine
        from seeing an empty team and ending the round.
        """
        game = self.game
        self.logger.info(
            "adroundextend: death fired victim=%s game=%s type=%s state=%s round_active=%s ext=%s",
            victim, game, game.type_short if game else None,
            game.state if game else None, self._round_active, self._extension_end
        )

        if not self._is_valid_game():
            self.logger.info("adroundextend: _is_valid_game() returned False — skipping")
            return
        if self._extension_end is not None:
            return  # extension already running

        teams = self.teams()
        self.logger.info(
            "adroundextend: teams red=%s blue=%s",
            [p.name for p in teams.get("red", [])],
            [p.name for p in teams.get("blue", [])]
        )

        # Work out which team the victim belongs to.
        victim_team = None
        for team_name in ("red", "blue"):
            if any(p.id == victim.id for p in teams[team_name]):
                victim_team = team_name
                break
        if victim_team is None:
            self.logger.info("adroundextend: victim not on red/blue — skipping")
            return

        # Count alive teammates EXCLUDING THE VICTIM because the death hook may
        # fire before the engine marks them as dead in player state.
        others_alive = sum(
            1 for p in teams[victim_team]
            if p.id != victim.id
            and (s := minqlxtended.player_state(p.id)) is not None
            and s.is_alive
        )
        self.logger.info(
            "adroundextend: victim=%s team=%s others_alive=%d",
            victim.name, victim_team, others_alive
        )
        if others_alive > 0:
            return  # other teammates still alive — nothing to do

        # Make sure the OTHER team still has alive players (avoid mutual-wipe extension).
        opposing = "blue" if victim_team == "red" else "red"
        if self._alive_count(teams.get(opposing, [])) == 0:
            self.logger.info("adroundextend: opposing team also empty — skipping")
            return

        # Last player on their team just died — extend the round.
        duration = self.get_cvar("qlx_adExtendDuration", float)
        self._extension_end = time.time() + duration
        self.logger.info("adroundextend: starting extension for %.1fs", duration)
        self.msg(
            "^2Round extended! "
            "^7{:.0f}^2 second{} to touch the flag!".format(
                duration, "s" if duration != 1 else ""
            )
        )
        self._spawn_ghost(victim)

    def handle_frame(self):
        self._frame_counter += 1
        if self._frame_counter < self._frame_interval:
            return
        self._frame_counter = 0

        if not self._is_valid_game():
            return
        if self._extension_end is None:
            return

        # ---- Manage an active extension --------------------------------
        now = time.time()
        if now >= self._extension_end:
            self._extension_end = None
            self._kill_ghost()
            self.msg("^1Extension over.")
        elif self._ghost_id is not None:
            state = minqlxtended.player_state(self._ghost_id)
            if state and state.is_alive:
                # Re-position underground and restore health every frame.
                # This prevents the engine from teleporting the ghost to a
                # spawn point and keeps them alive despite any hazard damage.
                minqlxtended.set_position(
                    self._ghost_id, minqlxtended.Vector3((0, 0, -10000))
                )
                minqlxtended.set_health(self._ghost_id, 1)
            else:
                # Ghost somehow died; respawn immediately.
                ghost_player = self.player(self._ghost_id)
                if ghost_player:
                    self._spawn_ghost(ghost_player)
