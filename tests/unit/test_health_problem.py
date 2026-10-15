import unittest

from lightcycle.domain.health import Problem


class TestProblemAsDict(unittest.TestCase):
    def test_kind_and_fix_serialise_when_set(self):
        d = Problem("config", "m", kind="k", fix="f").as_dict()
        self.assertEqual((d["kind"], d["fix"]), ("k", "f"))

    def test_kind_and_fix_are_omitted_when_unset(self):
        d = Problem("config", "m").as_dict()
        self.assertNotIn("kind", d)
        self.assertNotIn("fix", d)
