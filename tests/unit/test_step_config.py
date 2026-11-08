import unittest

from lightcycle.domain.workflows.step_config import step_config_keys, step_config_problems


class TestStepConfigKeys(unittest.TestCase):
    def test_a_valid_list(self):
        self.assertEqual(step_config_keys({"config": "[a, b-c]"}), ("a", "b-c"))

    def test_an_empty_list(self):
        self.assertEqual(step_config_keys({"config": "[]"}), ())

    def test_absent(self):
        self.assertEqual(step_config_keys({}), ())

    def test_malformed_values_raise(self):
        for bad in ({"a": "required"}, "a, b", "[a,, b]", "[a, a]", "[A]", "[a"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                step_config_keys({"config": bad})


class TestStepConfigProblems(unittest.TestCase):
    METAS = {"gate": {"config": "[limit]"}}
    STAGES = [("gate", "gate")]

    def test_a_shared_step_names_only_the_workflow_missing_the_key(self):
        a = step_config_problems("a", self.STAGES, self.METAS, ("limit",))
        b = step_config_problems("b", self.STAGES, self.METAS, ())
        self.assertEqual(a, [])
        self.assertEqual(len(b), 1)
        self.assertIn("'gate'", b[0])
        self.assertIn("'limit'", b[0])
        self.assertIn("workflow 'b'", b[0])

    def test_it_passes_when_both_declare_the_key(self):
        for wf in ("a", "b"):
            self.assertEqual(step_config_problems(wf, self.STAGES, self.METAS, ("limit",)), [])

    def test_a_malformed_list_is_reported(self):
        found = step_config_problems("a", self.STAGES, {"gate": {"config": "[x"}}, ("x",))
        self.assertEqual(len(found), 1)
        self.assertIn("config:", found[0])
