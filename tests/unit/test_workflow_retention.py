import unittest

from lightcycle.domain.workflows.retention import versions_to_prune


class TestVersionsToPrune(unittest.TestCase):
    def test_prunes_beyond_keep_n(self):
        versions = ["e", "d", "c", "b", "a"]
        self.assertEqual(versions_to_prune(versions, keep_n=2, pinned=set()),
                         ["c", "b", "a"])

    def test_keeps_all_when_within_keep_n(self):
        self.assertEqual(versions_to_prune(["b", "a"], keep_n=5, pinned=set()), [])

    def test_pinned_version_survives_beyond_keep_n(self):
        versions = ["e", "d", "c", "b", "a"]
        self.assertEqual(versions_to_prune(versions, keep_n=2, pinned={"a"}),
                         ["c", "b"])

    def test_pin_within_keep_n_is_not_double_counted(self):
        versions = ["c", "b", "a"]
        self.assertEqual(versions_to_prune(versions, keep_n=2, pinned={"c"}),
                         ["a"])

    def test_empty(self):
        self.assertEqual(versions_to_prune([], keep_n=2, pinned=set()), [])


if __name__ == "__main__":
    unittest.main()
