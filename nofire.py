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

import minqlxtended
import time


class nofire(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()
        self.nofire_until = {}  # steam_id → expire_time
        self._frame_interval = max(1, int(self.get_cvar("sv_fps")))
        self._frame_counter = 0
        self.add_command("nofire", self.cmd_nofire, 2, usage="<player>")
        self.add_command("nofireDuration", self.cmd_nofireDuration, 2, usage="<seconds>")
        self.add_hook("frame", self.handle_frame)
        minqlxtended.set_cvar("qlx_nofireDuration", "1.5")
        
        # Store original damage values
        self.damage_cvars = [
            "g_damage_sg_outer", "g_damage_sg_falloff", "g_damage_sg",
            "g_damage_rl", "g_damage_rg", "g_damage_pl", "g_damage_pg",
            "g_damage_ng", "g_damage_mg", "g_damage_lg", "g_damage_gl",
            "g_damage_hmg", "g_damage_gh", "g_damage_g", "g_damage_cg", "g_damage_bfg"
        ]
        self.original_damages = {}
        for cvar in self.damage_cvars:
            try:
                val = minqlxtended.get_cvar(cvar)
                self.original_damages[cvar] = val
                minqlxtended.log(f"Original {cvar}: {val}")
            except Exception as e:
                minqlxtended.log(f"Could not get {cvar}: {e}")
                self.original_damages[cvar] = "0"
        
        self.damages_disabled = False

    def handle_frame(self):
        """Check and restore damage values when nofire duration expires."""
        self._frame_counter += 1
        if self._frame_counter < self._frame_interval:
            return
        self._frame_counter = 0

        now = time.time()
        
        # Check if any nofire is active
        active_nofire = False
        expired_players = []
        
        for steam_id, expire_time in list(self.nofire_until.items()):
            if now >= expire_time:
                expired_players.append(steam_id)
            else:
                active_nofire = True
        
        for steam_id in expired_players:
            minqlxtended.log(f"Nofire expired for steam_id {steam_id}")
            del self.nofire_until[steam_id]
        
        # If no nofire active but damages are disabled, restore them
        if not active_nofire and self.damages_disabled:
            minqlxtended.log("Restoring damages")
            self.restore_damages()
            self.damages_disabled = False
        
        # If nofire is active but damages aren't disabled, disable them
        if active_nofire and not self.damages_disabled:
            minqlxtended.log("Disabling damages")
            self.disable_damages()
            self.damages_disabled = True

    def disable_damages(self):
        """Set all weapon damages to 0."""
        minqlxtended.log("Setting all weapon damages to 0")
        for cvar in self.damage_cvars:
            try:
                current = minqlxtended.get_cvar(cvar)
                minqlxtended.log(f"Before: {cvar} = {current}")
                minqlxtended.console_command(f"set {cvar} 0")
                after = minqlxtended.get_cvar(cvar)
                minqlxtended.log(f"After: {cvar} = {after}")
            except Exception as e:
                minqlxtended.log(f"Error setting {cvar}: {e}")

    def restore_damages(self):
        """Restore original weapon damage values."""
        minqlxtended.log("Restoring original weapon damages")
        for cvar in self.damage_cvars:
            try:
                val = str(self.original_damages[cvar])
                current = minqlxtended.get_cvar(cvar)
                minqlxtended.log(f"Before restore: {cvar} = {current}")
                minqlxtended.console_command(f"set {cvar} {val}")
                after = minqlxtended.get_cvar(cvar)
                minqlxtended.log(f"After restore: {cvar} = {after}")
            except Exception as e:
                minqlxtended.log(f"Error restoring {cvar}: {e}")

    def cmd_nofireDuration(self, player, msg, channel):
        """Set or view the nofire duration cvar."""
        if len(msg) > 1:
            try:
                value = float(msg[1])
                minqlxtended.set_cvar("qlx_nofireDuration", str(value))
                channel.reply(f"^2qlx_nofireDuration set to ^6{value}^2 seconds.")
            except ValueError:
                channel.reply("^1Invalid value. Must be a number.")
        else:
            duration = minqlxtended.get_cvar("qlx_nofireDuration")
            channel.reply(f"^2qlx_nofireDuration is set to ^6{duration}^2 seconds.")

    def cmd_nofire(self, player, msg, channel):
        """Disable firing for a player."""
        if len(msg) < 2:
            return minqlxtended.Return.USAGE
        
        target_player = self.player(msg[1])
        if not target_player:
            channel.reply("^1Player not found.")
            return
        
        seconds = None
        if len(msg) > 2:
            try:
                seconds = float(msg[2])
            except ValueError:
                channel.reply("^1Invalid duration. Must be a number.")
                return
        
        minqlxtended.log(f"cmd_nofire called for {target_player.name}")
        self.disable_fire(target_player, seconds)

    @minqlxtended.thread
    def disable_fire(self, player, seconds=None):
        """Disable weapon firing by setting all weapon damage values to 0."""
        if seconds is None:
            seconds = float(self.get_cvar("qlx_nofireDuration"))
        
        expire_time = time.time() + seconds
        self.nofire_until[player.steam_id] = expire_time
        minqlxtended.log(f"disable_fire: Added {player.name} (steam_id={player.steam_id}) to nofire_until, expires at {expire_time}")
        self.msg(f"^1{player.name} has disabled all weapon firing for {seconds} seconds.")
