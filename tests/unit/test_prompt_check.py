import unittest

from lightcycle.application.workflows.prompt_check import check_prompt_commands
from lightcycle.domain.contracts.cli_surface import cli_surface
from lightcycle.domain.contracts.json_surface import json_surface
from lightcycle.domain.contracts.prompt_commands import json_field_reads, lc_calls

_CLI = '''
def cmd_set(argv):
    ap = argparse.ArgumentParser(prog="lc set")
    for opt in ("title", "state", "needs", "reason"):
        ap.add_argument("--%s" % opt)
    ap.add_argument("--backlog", action="append")


def cmd_specs_dir(argv):
    ap = argparse.ArgumentParser(prog="lc specs-dir")
'''

_DOMAIN = '''
class Step:
    def as_dict(self):
        return {"id": self.id, "item": self.item, "stage": self.stage}


class NodeView:
    def as_dict(self):
        d = self.step.as_dict()
        d["item_artifacts"] = []
        return d
'''


class TestCliSurface(unittest.TestCase):
    def test_flags_come_from_argparse_including_loop_built_ones(self):
        s = cli_surface(_CLI)
        self.assertEqual(s["set"], {"title", "state", "needs", "reason", "backlog"})

    def test_a_hyphenated_verb_keeps_its_hyphen(self):
        self.assertIn("specs-dir", cli_surface(_CLI))


class TestJsonSurface(unittest.TestCase):
    def test_keys_come_from_the_read_surface_classes(self):
        keys = json_surface([_DOMAIN])
        self.assertEqual(keys, {"id", "item", "stage", "item_artifacts"})


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
        return check_prompt_commands({"s.md": text}, _CLI, [_DOMAIN]).get("s.md", [])

    def test_an_unknown_flag_is_refused(self):
        self.assertIn("does not accept --branch", self._check("`lc set X --branch b`")[0])

    def test_an_unknown_verb_is_refused(self):
        self.assertIn("is not a command", self._check("`lc frobnicate X`")[0])

    def test_a_state_missing_its_required_flag_is_refused(self):
        msgs = self._check('`lc set X --state blocked --needs "a"`')
        self.assertTrue(any("requires --reason" in m for m in msgs), msgs)

    def test_a_field_the_engine_does_not_emit_is_refused(self):
        self.assertIn("emits no `.parent`", self._check("take `.parent` as ITEM")[0])

    def test_a_correct_prompt_is_accepted(self):
        text = 'take `.item` as ITEM, then `lc set X --state blocked --needs "a" --reason "b"`'
        self.assertEqual(self._check(text), [])


if __name__ == "__main__":
    unittest.main()
