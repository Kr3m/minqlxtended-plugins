# 13/01/2025 - tjone270
# a minqlx plugin to list all players with a permission level greater than 0.

import minqlxtended


class permissionlist(minqlxtended.Plugin):
    def __init__(self):
        self.add_command("permissionlist", self.cmd_permissionlist, 5, usage="<level>")

    @minqlxtended.thread
    def cmd_permissionlist(self, player, msg, channel):
        """Lists all players with a permission level greater than 0."""

        players_permissions = {}
        for steam_id in self.db.smembers("minqlx:players"):
            key = "minqlx:players:{}:permission".format(steam_id)
            if not self.db.exists(key):
                continue
            steam_id = int(steam_id)
            permission = int(self.db.get(key))

            if permission > 0:
                players_permissions[steam_id] = permission

        players_permissions = dict(sorted(players_permissions.items(), key=lambda x: x[1]))

        channel.reply("^7Permissions list:")
        for steam_id, permission in players_permissions.items():
            channel.reply(" {}^7: ^2{}^7".format(steam_id, permission))
