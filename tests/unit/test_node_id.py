import unittest

from lightcycle.domain.work import node_id_key


class TestNodeIdKey(unittest.TestCase):
    def test_two_digit_step_suffix_sorts_after_one_digit_within_the_same_item(self):
        self.assertEqual(
            sorted(["LC-428.9", "LC-428.10", "LC-428.28"], key=node_id_key)[-1],
            "LC-428.28",
        )

    def test_step_suffix_comparison_is_numeric(self):
        self.assertGreater(node_id_key("LC-1.10"), node_id_key("LC-1.9"))

    def test_mixed_shortcodes_group_by_prefix(self):
        result = sorted(["SAGA-2", "LC-10", "LC-9", "FW-1"], key=node_id_key)
        lc_ids = [i for i in result if i.startswith("LC-")]
        self.assertEqual(lc_ids, ["LC-9", "LC-10"])

    def test_non_conforming_ids_sort_without_raising_and_match_plain_string_sort(self):
        ids = ["dg2", "ge0", "idm"]
        self.assertEqual(sorted(ids, key=node_id_key), sorted(ids))

    def test_item_sorts_before_its_own_step(self):
        self.assertLess(node_id_key("LC-9"), node_id_key("LC-9.1"))


if __name__ == "__main__":
    unittest.main()
