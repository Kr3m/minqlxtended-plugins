import minqlxtended
import os

class mapoo(minqlxtended.Plugin):

    def __init__(self):
        self.add_hook("player_connect", self.handle_player_connect)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch", self.handle_team_switch)

        self.mapoo_small_file = self.get_cvar("qlx_mapoo_small_file")
        self.mapoo_medium_file = self.get_cvar("qlx_mapoo_medium_file")
        self.mapoo_large_file = self.get_cvar("qlx_mapoo_large_file")
        self.mapoo_small_threshhold = int(self.get_cvar("qlx_mapoo_small_threshhold"))
        self.mapoo_medium_threshhold = int(self.get_cvar("qlx_mapoo_medium_threshhold"))
        self.mapoo_large_threshhold = int(self.get_cvar("qlx_mapoo_large_threshhold"))

        if not self.mapoo_small_file or not self.mapoo_medium_file or not self.mapoo_large_file or not self.mapoo_small_threshhold or not self.mapoo_medium_threshhold or not self.mapoo_large_threshhold:
            self.logger.error("mapoo cvar(s) missing or incorrect!")

    @minqlxtended.delay(2)
    def players_checker(self):
        player_count_in_game = 0

        for player in self.players():
            if player.team != "spectator":
                player_count_in_game += 1

        if self.mapoo_medium_threshhold > player_count_in_game >= self.mapoo_small_threshhold and self.mapoo_small_file != self.get_cvar("sv_mappoolfile"):
            self.set_cvar("sv_mappoolfile", self.mapoo_small_file)
            self.pool_changed()
        elif self.mapoo_large_threshhold > player_count_in_game >= self.mapoo_medium_threshhold and self.mapoo_medium_file != self.get_cvar("sv_mappoolfile"):
            self.set_cvar("sv_mappoolfile", self.mapoo_medium_file)
            self.pool_changed()
        elif player_count_in_game >= self.mapoo_large_threshhold and self.mapoo_large_file != self.get_cvar("sv_mappoolfile"):
            self.set_cvar("sv_mappoolfile", self.mapoo_large_file)
            self.pool_changed()

    def handle_player_connect(self, player, is_bot):
        self.players_checker()

    def handle_player_disconnect(self, player, reason):
        self.players_checker()

    def handle_team_switch(self, player, old_team, new_team):
        self.players_checker()

    def pool_changed(self):
        minqlxtended.console_command("reload_mappool")

        #If we are using nextmap plugin we want to reload the mappool list in essentials since it uses it for nextmaps!
        if "nextmap" in self.plugins:
            self.plugins['essentials'].mappool = None
            mphome = os.path.join(self.get_cvar("fs_homepath", str),
                "baseq3", self.get_cvar("sv_mappoolfile"))
            if os.path.isfile(mphome):
                self.plugins['essentials'].mappool = self.plugins['essentials'].parse_mappool(mphome)
            else:
                mpbase = os.path.join(self.get_cvar("fs_basepath", str),
                    "baseq3", self.get_cvar("sv_mappoolfile"))
                if os.path.isfile(mpbase):
                    self.plugins['essentials'].mappool = self.plugins['essentials'].parse_mappool(mpbase)
            self.plugins['nextmap'].handle_game_start()
