import unittest

from lightcycle.config_callouts import callout_blocks, callout_problems, valid_callouts

GOOD = {
    "command": "~/bin/x", "subject": "pr", "principal-outputs": "code",
    "wait": "true", "timeout": "30"}


def problems(**overrides):
    block = dict(GOOD)
    block.update(overrides)
    return callout_problems(block, "x")


class TestCalloutConfig(unittest.TestCase):
    def test_a_block_with_all_five_keys_parses(self):
        self.assertEqual(problems(), [])
        found, = valid_callouts({"x": GOOD}, lambda v: v.replace("~", "/home"))
        self.assertEqual(
            (found.id, found.command, found.subject, found.principal_outputs,
             found.wait, found.timeout),
            ("x", "/home/bin/x", "pr", ("code",), True, 30))

    def test_blocks_are_read_from_callout_prefixed_dict_keys_only(self):
        values = {"callout-a": {"command": "c"}, "callout-b": "scalar", "other": {"k": "v"}}
        self.assertEqual(callout_blocks(values), {"a": {"command": "c"}})

    def test_each_missing_or_blank_key_names_the_key(self):
        for key in GOOD:
            block = {k: v for k, v in GOOD.items() if k != key}
            self.assertTrue(any(repr(key) in p for p in callout_problems(block, "x")), key)
            self.assertTrue(any(repr(key) in p for p in problems(**{key: "  "})), key)

    def test_a_block_without_principal_outputs_names_the_key(self):
        block = {k: v for k, v in GOOD.items() if k != "principal-outputs"}
        self.assertTrue(any("'principal-outputs'" in p for p in callout_problems(block, "x")))

    def test_principal_outputs_must_be_kebab_names(self):
        for bad in ("Spec", "a b", ","):
            self.assertTrue(
                any("'principal-outputs'" in p for p in problems(**{"principal-outputs": bad})),
                bad)

    def test_principal_outputs_accepts_a_list(self):
        found, = valid_callouts(
            {"x": dict(GOOD, **{"principal-outputs": "spec, code"})}, lambda v: v)
        self.assertEqual(found.principal_outputs, ("spec", "code"))

    def test_a_bad_id_is_a_problem(self):
        self.assertTrue(callout_problems(dict(GOOD), "Bad_Id"))

    def test_a_bad_subject_is_a_problem(self):
        for subject in ("artifact:", "step", "tab:log"):
            self.assertTrue(any("'subject'" in p for p in problems(subject=subject)), subject)

    def test_artifact_subjects_with_a_name_are_valid(self):
        self.assertEqual(problems(subject="artifact:spec"), [])

    def test_a_non_boolean_wait_is_a_problem(self):
        self.assertTrue(any("'wait'" in p for p in problems(wait="maybe")))

    def test_a_timeout_of_zero_or_text_is_a_problem(self):
        self.assertTrue(any("'timeout'" in p for p in problems(timeout="0")))
        self.assertTrue(any("'timeout'" in p for p in problems(timeout="abc")))

    def test_an_unknown_key_is_a_problem(self):
        self.assertTrue(any("'colour'" in p for p in problems(colour="red")))

    def test_an_invalid_block_is_never_returned_as_a_callout(self):
        self.assertEqual(valid_callouts({"x": dict(GOOD, timeout="0")}, lambda v: v), [])
