"""Regression tests for myessentials player commands on minqlxtended.

minqlxtended removed classic minqlx's Plugin convenience wrappers (switch, slap,
slay, shuffle, pause, unpause, lock, unlock, allready, abort) — they live on Game
now — and its Plugin.player() raises NonexistentPlayerError for an empty client
slot. Both made "!switch <id> <id>" (and friends) and "!spec <bad id>" fail
silently. The fake framework below mirrors exactly those minqlxtended semantics.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class NonexistentPlayerError(Exception):
    pass


class FakeGame:
    """Mirrors the minqlxtended Game methods the plugin relies on."""

    def __init__(self, plugin):
        self._plugin = plugin
        self.calls = []

    def switch(self, player, other_player):
        if player.team == other_player.team:
            raise ValueError("Both players are on the same team.")
        player.team, other_player.team = other_player.team, player.team
        self.calls.append(("switch", player, other_player))

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name,) + args)
        return record


class FakePlayer:
    def __init__(self, client_id, name, team="spectator"):
        self.id = client_id
        self.name = name
        self.steam_id = 76561190000000000 + client_id
        self.team = team
        self.told = []

    @property
    def clean_name(self):
        return re.sub(r"\^[0-9]", "", self.name)

    def tell(self, msg, **kwargs):
        self.told.append(msg)

    def put(self, team):
        self.team = team

    def __eq__(self, other):
        if isinstance(other, FakePlayer):
            return self.steam_id == other.steam_id
        return self.steam_id == other

    def __hash__(self):
        return hash(self.steam_id)


class FakePlugin:
    """Deliberately has no switch/slap/slay/... wrappers, like minqlxtended."""

    roster = []

    def __init__(self):
        self.game = FakeGame(self)

    def players(self):
        return list(self.roster)

    def player(self, name, player_list=None):
        if isinstance(name, FakePlayer):
            return name
        if isinstance(name, int) and 0 <= name < 64:
            for p in self.players():
                if p.id == name:
                    return p
            # Real minqlxtended raises for an in-range but empty client slot.
            raise NonexistentPlayerError("The player does not exist.")
        return None

    def find_player(self, name, player_list=None):
        players = self.players() if player_list is None else player_list
        if not name:
            return players
        needle = self.clean_text(name).lower()
        return [p for p in players if needle in p.clean_name.lower()]

    @staticmethod
    def clean_text(text):
        return re.sub(r"\^[0-9]", "", text)

    def after_command(self, func):
        func()


def make_framework():
    framework = ModuleType("minqlxtended")
    framework.Plugin = FakePlugin
    framework.NonexistentPlayerError = NonexistentPlayerError
    framework.Return = SimpleNamespace(STOP=0, STOP_EVENT=1, STOP_ALL=2, USAGE=3, NONE=4)
    framework.Priority = SimpleNamespace(LOW=1, NORMAL=2)
    framework.CHAT_CHANNEL = Mock()
    framework.thread = lambda func: func
    framework.next_frame = lambda func: func
    framework.delay = lambda seconds: lambda func: func
    database = ModuleType("minqlxtended.database")
    database.Redis = object
    framework.database = database
    return framework, database


def load_plugins():
    framework, database = make_framework()
    requests = ModuleType("requests")
    requests.get = Mock(side_effect=AssertionError("Tests must not download plugins"))
    package_name = "myessentials_commands_test"
    package = ModuleType(package_name)
    package.__path__ = []
    root = Path(__file__).resolve().parents[1]
    modules = {
        package_name: package,
        "minqlxtended": framework,
        "minqlxtended.database": database,
        "requests": requests,
    }
    with patch.dict(sys.modules, modules):
        for name in ("iouonegirl", "myessentials"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{name}", root / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"{package_name}.{name}"] = module
            spec.loader.exec_module(module)
    return module.myessentials, framework


class TestMyessentialsCommands(unittest.TestCase):
    def setUp(self):
        cls, self.framework = load_plugins()
        self.plugin = cls.__new__(cls)
        self.plugin.game = FakeGame(self.plugin)
        self.red = FakePlayer(3, "RedGuy", team="red")
        self.blue = FakePlayer(7, "BlueGuy", team="blue")
        self.blue2 = FakePlayer(9, "BlueMate", team="blue")
        FakePlugin.roster = [self.red, self.blue, self.blue2]
        self.caller = FakePlayer(0, "Admin")
        self.channel = Mock()

    def test_spec_by_numeric_id(self):
        self.plugin.cmd_spectate(self.caller, ["!spec", "3"], self.channel)
        self.assertEqual(self.red.team, "spectator")

    def test_spec_by_name_still_works(self):
        self.plugin.cmd_spectate(self.caller, ["!spec", "bluegu"], self.channel)
        self.assertEqual(self.blue.team, "spectator")

    def test_spec_nonexistent_id_fails_with_message(self):
        result = self.plugin.cmd_spectate(self.caller, ["!spec", "31"], self.channel)
        self.assertEqual(result, self.framework.Return.STOP_EVENT)
        self.assertTrue(any("no players matched" in m for m in self.caller.told))
        self.assertEqual(self.red.team, "red")

    def test_switch_by_numeric_ids(self):
        self.plugin.cmd_switch(self.caller, ["!switch", "3", "7"], self.channel)
        self.assertEqual((self.red.team, self.blue.team), ("blue", "red"))

    def test_switch_same_team_replies_instead_of_raising(self):
        result = self.plugin.cmd_switch(self.caller, ["!switch", "7", "9"], self.channel)
        self.assertEqual(result, self.framework.Return.STOP_EVENT)
        self.assertIn("same team", self.channel.reply.call_args.args[0])

    def test_game_wrappers_route_through_game(self):
        self.plugin.cmd_shuffle(self.caller, ["!shuffle"], self.channel)
        self.plugin.cmd_slay(self.caller, ["!slay", "7"], self.channel)
        self.plugin.cmd_slap(self.caller, ["!slap", "3", "25"], self.channel)
        self.plugin.cmd_lock(self.caller, ["!lock", "red"], self.channel)
        self.assertEqual(
            self.plugin.game.calls,
            [
                ("shuffle",),
                ("slay", self.blue),
                ("slap", self.red, 25),
                ("lock", "red"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
