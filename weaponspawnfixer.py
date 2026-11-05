import minqlxtended

class weaponspawnfixer(minqlxtended.Plugin):

    def __init__(self):

        self.add_hook("game_start", self.handle_game_start)
        self.add_hook("new_game", self.handle_new_game)

    @minqlxtended.delay(2)
    def handle_new_game(self):
        minqlxtended.force_weapon_respawn_time(int(self.get_cvar("g_weaponrespawn")))

    @minqlxtended.delay(2)
    def handle_game_start(self):
        minqlxtended.force_weapon_respawn_time(int(self.get_cvar("g_weaponrespawn")))
