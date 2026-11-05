# captain.py - Designate spectators as team captains.
# Commands:
#   !captain <client_id> red
#   !captain <client_id> blue
#
# Requires permission level 2+

import minqlxtended

class captain(minqlxtended.Plugin):
    database = minqlxtended.database.Redis

    def __init__(self):
        super().__init__()

        self._captains = {"red": None, "blue": None}

        self.add_command("captain", self.cmd_captain, 2, client_cmd_perm=2)

    def cmd_captain(self, player, msg, channel):
        """
        Usage: !captain <client_id> <red|blue>
        """
        if len(msg) != 3:
            return minqlxtended.Return.USAGE

        try:
            target_id = int(msg[1])
        except ValueError:
            player.tell("^1Invalid client ID.")
            return minqlxtended.Return.STOP_ALL

        team_arg = msg[2].lower()
        if team_arg not in ("red", "blue"):
            player.tell("^1Team must be 'red' or 'blue'.")
            return minqlxtended.Return.STOP_ALL

        target = self.player(target_id)
        if not target:
            player.tell(f"^1No player with client ID {target_id}.")
            return minqlxtended.Return.STOP_ALL

        if target.team != "spectator":
            player.tell(f"^1{target.clean_name} ^1must be a spectator to be assigned as captain.")
            return minqlxtended.Return.STOP_ALL

        self._captains[team_arg] = target.steam_id

        team_color = "^1RED" if team_arg == "red" else "^4BLUE"
        self.msg(f"{target.name} ^7is now captain for {team_color}^7.")

        return minqlxtended.Return.STOP_ALL
