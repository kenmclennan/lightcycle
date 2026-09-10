import unittest

from lightcycle.application.workflows.prompt_check import check_prompt_commands
from lightcycle.application.workflows.prompt_commands import json_field_reads, lc_calls
from lightcycle.cli_commands import Arg, CommandSpec, flags_by_verb
from lightcycle.domain.contracts.json_surface import json_surface

_COMMANDS = {
    "set": CommandSpec(prog="lc set", args=(
        Arg("--title"), Arg("--state"), Arg("--needs"), Arg("--reason"),
        Arg("--backlog", action="append"),
    )),
    "specs-dir": CommandSpec(prog="lc specs-dir"),
}

_SURFACE = flags_by_verb(_COMMANDS)
_JSON_KEYS = {"id", "item", "stage", "item_artifacts"}


class TestCliSurface(unittest.TestCase):
    def test_flags_come_from_declared_args(self):
        self.assertEqual(_SURFACE["set"], {"title", "state", "needs", "reason", "backlog"})

    def test_a_hyphenated_verb_keeps_its_hyphen(self):
        self.assertIn("specs-dir", _SURFACE)


class TestJsonSurface(unittest.TestCase):
    def test_keys_come_from_the_real_read_surface_classes(self):
        keys = json_surface()
        self.assertIn("id", keys)
        self.assertIn("item", keys)
        self.assertIn("item_artifacts", keys)


class TestExtractingCallsFromProse(unittest.TestCase):
    def test_only_backticked_commands_count(self):
        text = "lc already created the worktree; run `lc set X --title y`"
        self.assertEqual([c["verb"] for c in lc_calls(text)], ["set"])

    def test_a_flag_inside_a_quoted_argument_is_not_a_flag(self):
        text = '`lc set X --needs "run gh pr list --head BRANCH"`'
        self.assertEqual(lc_calls(text)[0]["flags"], {"needs"})

    def test_a_file_extension_is_not_a_field_read(self):
        text = "the merged `.feature` scenarios are frozen"
        self.assertEqual(json_field_reads(text), [])

    def test_a_field_read_is_found(self):
        self.assertEqual(
            [r["field"] for r in json_field_reads("take `.parent` as ITEM")], ["parent"]
        )


class TestCheckRefusals(unittest.TestCase):
    def _check(self, text):
        return check_prompt_commands({"s.md": text}, _SURFACE, _JSON_KEYS).get("s.md", [])

    def test_an_unknown_flag_is_refused(self):
        self.assertIn("does not accept --branch", self._check("`lc set X --branch b`")[0])

    def test_an_unknown_verb_is_refused(self):
        self.assertIn("is not a command", self._check("`lc frobnicate X`")[0])

    def test_a_state_missing_its_required_flag_is_refused(self):
        msgs = self._check('`lc set X --state waiting --needs "a"`')
        self.assertTrue(any("requires --reason" in m for m in msgs), msgs)

    def test_a_field_the_engine_does_not_emit_is_refused(self):
        self.assertIn("emits no `.parent`", self._check("take `.parent` as ITEM")[0])

    def test_a_correct_prompt_is_accepted(self):
        text = 'take `.item` as ITEM, then `lc set X --state waiting --needs "a" --reason "b"`'
        self.assertEqual(self._check(text), [])


if __name__ == "__main__":
    unittest.main()
