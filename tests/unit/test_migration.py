import unittest

from the_grid.domain.work import MigratedTask, seed_counters


class TestSeedCounters(unittest.TestCase):
    def test_seeds_child_namespace_above_max_suffix(self):
        tasks = [
            MigratedTask(id="the-grid-abc", type="story"),
            MigratedTask(id="the-grid-abc.1", type="task", parent="the-grid-abc"),
            MigratedTask(id="the-grid-abc.3", type="task", parent="the-grid-abc"),
        ]
        seeds = seed_counters(tasks, "GRID")
        self.assertEqual(seeds["the-grid-abc"], 4)

    def test_no_seed_for_namespace_without_numeric_children(self):
        tasks = [MigratedTask(id="the-grid-abc", type="story")]
        seeds = seed_counters(tasks, "GRID")
        self.assertEqual(seeds, {})

    def test_seeds_shortcode_namespace_when_ids_collide_in_pattern(self):
        tasks = [MigratedTask(id="GRID-5", type="task")]
        seeds = seed_counters(tasks, "GRID")
        self.assertEqual(seeds["GRID"], 6)


if __name__ == "__main__":
    unittest.main()
