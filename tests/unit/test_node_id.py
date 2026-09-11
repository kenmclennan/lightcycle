import unittest

from lightcycle.domain.work import node_id_key
from lightcycle.domain.work.node_id import _STEP_RE, format_step_id


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


class TestFormatStepId(unittest.TestCase):
    def test_round_trips_through_step_re_for_a_range_of_ids_and_ns(self):
        for item_id in ("LC-1", "LC-616", "ABC-42", "X-9999"):
            for n in (1, 2, 9, 10, 99, 100):
                formatted = format_step_id(item_id, n)
                m = _STEP_RE.match(formatted)
                self.assertIsNotNone(m, formatted)
                prefix, item_n, step_n = m.groups()
                self.assertEqual("%s-%s" % (prefix, item_n), item_id)
                self.assertEqual(int(step_n), n)

    def test_matches_the_literal_current_composition(self):
        self.assertEqual(format_step_id("LC-616", 3), "LC-616.3")


if __name__ == "__main__":
    unittest.main()
