import importlib.util
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class FakePlugin:
    def __init__(self):
        self.cvars = {}
        self.logger = Mock(spec=logging.Logger)
        self.add_command = Mock()
        self.add_hook = Mock()
        self.game = SimpleNamespace(factory="current_ft")
        self.vote_active = False

    def set_cvar_once(self, name, value):
        self.cvars.setdefault(name, value)

    def get_cvar(self, name):
        value = self.cvars.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    def is_vote_active(self):
        return self.vote_active


def load_plugin(runtime):
    framework = ModuleType(runtime)
    framework.Plugin = FakePlugin
    framework.NonexistentGameError = type("NonexistentGameError", (Exception,), {})
    framework.Priority = SimpleNamespace(HIGHEST=0)
    framework.Return = SimpleNamespace(STOP_ALL=3, USAGE=4)
    framework.PRI_HIGHEST = 0
    framework.RET_STOP_ALL = 3
    framework.RET_USAGE = 4
    framework.client_command = Mock()
    framework.map_info = Mock(return_value=None)
    source = Path(__file__).resolve().parents[1] / "mymaps.py"
    spec = importlib.util.spec_from_file_location("mymaps_vote_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"minqlxtended": None, "minqlx": None, runtime: framework}):
        spec.loader.exec_module(module)
    return module


class TestMapVotes(unittest.TestCase):
    runtime = "minqlxtended"

    def setUp(self):
        self.module = load_plugin(self.runtime)
        self.plugin = self.module.mymaps()
        self.caller = SimpleNamespace(id=1, name="Player")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.pool = Path(self.directory.name) / "pool.txt"
        self.pool.write_text("realmofsteelrats|vft\ncampgrounds|ca\n", encoding="utf-8")
        self.plugin.cvars.update(sv_mapPoolFile=str(self.pool), g_voteFlags="0")
        self.commands = []
        self.accept = lambda command: True
        self.module.minqlx.client_command.side_effect = self.execute

    def execute(self, caller_id, command):
        self.assertEqual(caller_id, self.caller.id)
        self.commands.append(command)
        _, vote, *parts = command.split()
        result = self.plugin.handle_vote_called(self.caller, vote, " ".join(parts))
        self.assertIsNone(result, "Reissued votes must not recursively rewrite")
        self.plugin.vote_active = self.accept(command)
        return True

    def call(self, args="", vote="map"):
        return self.plugin.handle_vote_called(self.caller, vote, args)

    def test_registration_and_diagnostics_before_any_early_return(self):
        self.plugin.add_hook.assert_called_once_with("vote_called", self.plugin.handle_vote_called)
        self.plugin.cvars["qlx_mymaps_vote_enable"] = "0"
        self.call("", "realmofsteelrats")
        self.plugin.logger.info.assert_any_call(
            "vote_called ENTER: vote='realmofsteelrats' args='' caller=Player"
        )
        self.plugin.handle_vote_called(None, "map", "realmofsteelrats")
        self.plugin.logger.info.assert_any_call(
            "vote_called ENTER: vote='map' args='realmofsteelrats' caller=server"
        )
        self.assertEqual(self.commands, [])

    def test_pool_resolution_for_both_forms_blocks_original(self):
        for vote, args in [("realmofsteelrats", ""), ("map", "realmofsteelrats")]:
            with self.subTest(vote=vote):
                self.plugin.vote_active = False
                self.commands.clear()
                self.assertEqual(self.call(args, vote), self.module.STOP_ALL)
                self.assertEqual(self.commands, ["callvote map realmofsteelrats vft"])
                self.plugin.logger.info.assert_any_call(
                    "Map vote '%s': %s factory '%s'; rewritten=yes.",
                    "realmofsteelrats", "pool", "vft"
                )

    def test_rewrite_diagnostics_bracket_actual_command_and_report_stop(self):
        events = []
        self.plugin.logger.info.side_effect = lambda message, *args: events.append(message)

        def execute(caller_id, command):
            events.append("COMMAND entered")
            result = self.execute(caller_id, command)
            events.append("COMMAND returned")
            return result

        self.module.minqlx.client_command.side_effect = execute
        self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
        before = "REWRITING vote: map='realmofsteelrats' factory='vft'"
        self.assertLess(events.index(before), events.index("COMMAND entered"))
        self.assertLess(events.index("COMMAND returned"), events.index("REWRITE client_command sent"))
        self.assertEqual(events[-1], "vote_called EXIT: returning STOP_ALL after rewrite/replay.")
        self.plugin.logger.info.assert_any_call(
            "Vote command result: command=%r delivered=%r active=%r.",
            "callvote map realmofsteelrats vft", True, True
        )

    def test_failed_rewrite_does_not_log_successful_send(self):
        def execute(caller_id, command):
            if command.endswith(" vft"):
                raise RuntimeError("command failed")
            return self.execute(caller_id, command)

        self.module.minqlx.client_command.side_effect = execute
        self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
        messages = [entry.args[0] for entry in self.plugin.logger.info.call_args_list]
        self.assertNotIn("REWRITE client_command sent", messages)
        self.assertIn("Original vote replay client_command sent", messages)
        self.assertEqual(self.commands, ["callvote map realmofsteelrats"])

    def test_default_and_current_for_canonical_and_installed_shorthand(self):
        self.module.minqlx.map_info.return_value = SimpleNamespace(name="unlisted")
        for default, expected in [("ft_duel", "ft_duel"), ("", "current_ft")]:
            for vote, args in [("map", "unlisted"), ("unlisted", "")]:
                with self.subTest(default=default, vote=vote):
                    self.plugin.vote_active = False
                    self.commands.clear()
                    self.plugin.cvars["qlx_defaultFactory"] = default
                    self.assertEqual(self.call(args, vote), self.module.STOP_ALL)
                    self.assertEqual(self.commands, [f"callvote map unlisted {expected}"])

    def test_explicit_factory_bypasses_pool_and_reissuance(self):
        with patch.object(self.plugin, "_parse_map_pool", side_effect=AssertionError("not needed")):
            self.assertIsNone(self.call("realmofsteelrats ft_duel"))
        self.assertEqual(self.commands, [])
        self.plugin.logger.info.assert_called_with(
            "Map vote '%s': %s factory '%s'; rewritten=no.",
            "realmofsteelrats", "explicit", "ft_duel"
        )

    def test_live_toggle_is_independent_of_map_command(self):
        self.plugin.cvars["qlx_mymaps_enable"] = "0"
        for enabled, expected in [("0", None), ("1", self.module.STOP_ALL)]:
            self.plugin.cvars["qlx_mymaps_vote_enable"] = enabled
            self.assertEqual(self.call("realmofsteelrats"), expected)
        self.assertEqual(self.commands, ["callvote map realmofsteelrats vft"])

    def test_cvar_read_failure_defaults_enabled(self):
        self.plugin.cvars["qlx_mymaps_vote_enable"] = RuntimeError("unavailable")
        self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
        self.plugin.logger.warning.assert_called()

    def test_server_caller_and_failed_shorthand_identification_are_untouched(self):
        self.assertIsNone(self.plugin.handle_vote_called(None, "map", "realmofsteelrats"))
        self.module.minqlx.map_info.side_effect = OSError("map cache unavailable")
        self.assertIsNone(self.call("", "unlisted"))
        del self.module.minqlx.map_info
        self.assertIsNone(self.call("", "unlisted"))
        self.assertEqual(self.commands, [])

    def test_pool_failure_and_missing_factory_leave_original_untouched(self):
        self.pool.unlink()
        self.plugin.cvars["qlx_defaultFactory"] = "ft"
        self.assertIsNone(self.call("realmofsteelrats"))
        self.pool.write_text("", encoding="utf-8")
        self.plugin.cvars["qlx_defaultFactory"] = ""
        self.plugin.game = None
        self.assertIsNone(self.call("realmofsteelrats"))
        self.assertEqual(self.commands, [])
        self.plugin.logger.warning.assert_called()

    def test_unreadable_pool_leaves_original_untouched(self):
        with patch("builtins.open", side_effect=PermissionError("denied")):
            self.assertIsNone(self.call("realmofsteelrats"))
        self.assertEqual(self.commands, [])

    def test_bit_eight_and_unreadable_flags_skip_rewriting(self):
        for flags in ("8", "24", "invalid", None, RuntimeError("unavailable")):
            with self.subTest(flags=flags):
                self.plugin.cvars["g_voteFlags"] = flags
                self.assertIsNone(self.call("realmofsteelrats"))
                self.assertEqual(self.commands, [])
                self.plugin.logger.warning.assert_called()

    def test_rejected_rewrite_replays_original_once_and_blocks_outer_call(self):
        self.accept = lambda command: command == "callvote map realmofsteelrats"
        self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
        self.assertEqual(self.commands, [
            "callvote map realmofsteelrats vft", "callvote map realmofsteelrats"
        ])
        self.assertTrue(self.plugin.vote_active)
        self.assertFalse(self.plugin._reissuing_vote)
        self.plugin.logger.error.assert_called()

    def test_rejected_shorthand_replays_exact_original_form(self):
        self.accept = lambda command: False
        self.assertEqual(self.call("", "realmofsteelrats"), self.module.STOP_ALL)
        self.assertEqual(self.commands, [
            "callvote map realmofsteelrats vft", "callvote realmofsteelrats"
        ])
        self.assertEqual(self.plugin.logger.error.call_count, 2)

    def test_rewrite_exception_and_failed_delivery_replay_original(self):
        for failure in (RuntimeError("unavailable"), False):
            with self.subTest(failure=failure):
                self.plugin.vote_active = False
                self.module.minqlx.client_command.side_effect = [failure, True]
                self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
                self.assertEqual(self.module.minqlx.client_command.call_count, 2)
                self.assertFalse(self.plugin._reissuing_vote)
                self.module.minqlx.client_command.reset_mock()

    def test_exception_after_vote_started_does_not_replay_over_active_vote(self):
        def execute_then_raise(caller_id, command):
            self.execute(caller_id, command)
            raise RuntimeError("error after vote started")

        self.module.minqlx.client_command.side_effect = execute_then_raise
        self.assertEqual(self.call("realmofsteelrats"), self.module.STOP_ALL)
        self.assertEqual(self.commands, ["callvote map realmofsteelrats vft"])
        self.assertFalse(self.plugin._reissuing_vote)

    def test_unrelated_votes_invalid_arguments_and_active_vote_are_untouched(self):
        for vote, args in [("shuffle", ""), ("kick", "1"), ("custom", "value"), ("map", ""),
                           ("map", "realmofsteelrats ca extra")]:
            with self.subTest(vote=vote, args=args):
                self.assertIsNone(self.call(args, vote))
        self.plugin.vote_active = True
        self.assertIsNone(self.call("realmofsteelrats"))
        self.assertEqual(self.commands, [])

    def test_unsafe_factory_and_map_are_never_reissued(self):
        self.plugin.cvars["qlx_defaultFactory"] = "ca;quit"
        for args in ("unlisted", "map;quit"):
            self.assertIsNone(self.call(args))
        self.assertEqual(self.commands, [])

    def test_case_and_whitespace(self):
        self.assertEqual(self.call(" \tREALMOFSTEELRATS  ", "MAP"), self.module.STOP_ALL)
        self.assertEqual(self.commands, ["callvote map REALMOFSTEELRATS vft"])

    def test_redundant_map_keyword_and_whitespace_are_normalized(self):
        for vote, args in [
            ("map", "map realmofsteelrats"),
            (" \tMAP ", " \tMaP  REALMOFSTEELRATS \t"),
            (" realmofsteelrats ", " \t"),
        ]:
            with self.subTest(vote=vote, args=args):
                self.plugin.vote_active = False
                self.commands.clear()
                self.assertEqual(self.call(args, vote), self.module.STOP_ALL)
                self.assertEqual(len(self.commands), 1)
                self.assertEqual(
                    self.commands[0].lower(), "callvote map realmofsteelrats vft"
                )

    def test_redundant_map_keyword_keeps_explicit_factory_untouched(self):
        self.assertIsNone(self.call(" MAP realmofsteelrats ft_duel ", " map "))
        self.assertEqual(self.commands, [])
        self.plugin.logger.info.assert_called_with(
            "Map vote '%s': %s factory '%s'; rewritten=no.",
            "realmofsteelrats", "explicit", "ft_duel"
        )

    def test_missing_map_after_keyword_and_extra_arguments_are_untouched(self):
        for args in ("map", " MAP ", "map realmofsteelrats ca extra"):
            with self.subTest(args=args):
                self.assertIsNone(self.call(args))
        self.assertEqual(self.commands, [])
        self.plugin.logger.warning.assert_called()


class TestLegacyMapVotes(TestMapVotes):
    runtime = "minqlx"


if __name__ == "__main__":
    unittest.main()
