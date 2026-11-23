import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from test_mymaps_vote import load_plugin


def load_myessentials(framework):
    package_name = "mappool_policy_test"
    package = ModuleType(package_name)
    package.__path__ = []
    base = ModuleType(f"{package_name}.iouonegirl")
    base.iouonegirlPlugin = object
    database = ModuleType("minqlxtended.database")
    database.Redis = object
    framework.database = database
    framework.delay = lambda seconds: lambda function: function
    requests = ModuleType("requests")
    requests.get = Mock(side_effect=AssertionError("Tests must not download plugins"))
    source = Path(__file__).resolve().parents[1] / "myessentials.py"
    spec = importlib.util.spec_from_file_location(f"{package_name}.myessentials", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        package_name: package,
        base.__name__: base,
        "minqlxtended": framework,
        "minqlxtended.database": database,
        "requests": requests,
    }):
        spec.loader.exec_module(module)
    return module.myessentials.__new__(module.myessentials)


class TestMyessentialsMappool(unittest.TestCase):
    def setUp(self):
        self.module = load_plugin("minqlxtended")
        self.maps = self.module.mymaps()
        self.policy = load_myessentials(self.module.minqlx)
        self.policy.mappool = {"realmofsteelrats": ["vft"]}
        self.policy.game = SimpleNamespace(factory="ft_competitive")
        self.policy.change_map = Mock()
        self.maps.change_map = Mock()
        self.policy.get_cvar = self.get_cvar
        self.maps.cvars.update(
            qlx_enforceMappool="1", qlx_votepass="0", qlx_commandPrefix="!",
            g_voteFlags="0", qlx_defaultFactory="ft_competitive",
        )
        self.caller = SimpleNamespace(id=1, name="Player", tell=Mock())
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        pool = Path(self.directory.name) / "pool.txt"
        pool.write_text("realmofsteelrats|vft\n", encoding="utf-8")
        self.maps.cvars["sv_mapPoolFile"] = str(pool)

    def get_cvar(self, name, value_type=str):
        value = self.maps.cvars.get(name)
        if value_type is bool:
            return value == "1"
        return value_type(value) if value is not None else None

    def test_omitted_factory_does_not_validate_current_factory(self):
        self.assertIsNone(self.policy.handle_vote_called(self.caller, "map", "realmofsteelrats"))
        self.caller.tell.assert_not_called()

    def test_explicit_factory_must_be_allowed_by_pool(self):
        for factory, expected in [("vft", None), ("ft_duel", self.module.STOP_ALL)]:
            with self.subTest(factory=factory):
                result = self.policy.handle_vote_called(
                    self.caller, "map", f"realmofsteelrats {factory}"
                )
                self.assertEqual(result, expected)

    def test_out_of_pool_map_is_still_rejected(self):
        for args in ("unlisted", "unlisted vft"):
            with self.subTest(args=args):
                self.assertEqual(
                    self.policy.handle_vote_called(self.caller, "map", args),
                    self.module.STOP_ALL,
                )
        self.assertIn("This map is not allowed", self.caller.tell.call_args.args[0])

    def test_disabled_enforcement_still_allows_votes(self):
        self.maps.cvars["qlx_enforceMappool"] = "0"
        self.assertIsNone(self.policy.handle_vote_called(self.caller, "map", "unlisted ft_duel"))

    def test_pool_factory_rewrite_works_in_either_hook_order(self):
        for policy_first in (True, False):
            with self.subTest(policy_first=policy_first):
                self.maps.vote_active = False
                self.caller.tell.reset_mock()
                accepted = []
                handlers = [self.policy.handle_vote_called, self.maps.handle_vote_called]
                if not policy_first:
                    handlers.reverse()

                def dispatch(vote, args):
                    for handler in handlers:
                        if handler(self.caller, vote, args) == self.module.STOP_ALL:
                            return
                    accepted.append((vote, args))
                    self.maps.vote_active = True

                def execute(caller_id, command):
                    self.assertEqual(caller_id, self.caller.id)
                    _, vote, args = command.split(None, 2)
                    dispatch(vote, args)
                    return True

                self.module.minqlx.client_command.side_effect = execute
                dispatch("map", "realmofsteelrats")
                self.assertEqual(accepted, [("map", "realmofsteelrats vft")])
                self.caller.tell.assert_not_called()

    def test_administrative_map_exemption_is_preserved(self):
        channel = Mock()
        self.maps.cmd_map(self.caller, ["!map", "realmofsteelrats"], channel)
        self.maps.change_map.assert_called_with("realmofsteelrats", "vft")
        self.maps.cmd_map(self.caller, ["!map", "unlisted"], channel)
        self.maps.change_map.assert_called_with("unlisted", "ft_competitive")
        self.policy.cmd_map(self.caller, ["!map", "unlisted"], channel)
        self.policy.change_map.assert_called_with("unlisted", None)


if __name__ == "__main__":
    unittest.main()
