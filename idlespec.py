
import minqlxtended

class idlespec(minqlxtended.Plugin):
    def __init__(self):
        super().__init__()
        self.logger.warning(
            "idlespec disabled: minqlxtended has no player_inactivity_kick hook."
        )
