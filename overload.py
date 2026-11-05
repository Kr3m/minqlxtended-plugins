import minqlxtended

class overload(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()

        self.add_hook("map", self.handle_map_change)

    def handle_map_change(self, mapname: str, factory: str) -> None:
        @minqlxtended.delay(12)
        def map_restart():
            minqlxtended.console_command("map_restart")
            
        if factory not in ["ol", "olad", "olca", "olctf"]:
            return

        minqlxtended.set_cvar("g_gametype", "7", -1)
        map_restart()
