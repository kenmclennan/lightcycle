import json
import os
import tempfile
import unittest

from lightcycle.adapters.github_budget_status import GithubBudgetStatusAdapter
from lightcycle.domain.pool import GithubBudget


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestGithubBudgetStatusAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, "logs", "github_budget.json")
        self.status = GithubBudgetStatusAdapter(FakeConfig(self.root))

    def _write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(text)

    def test_load_with_no_state_file_is_none(self):
        self.assertIsNone(self.status.load())

    def test_save_then_load_round_trips(self):
        budget = GithubBudget(limit=5000, remaining=4261, reset=1792503970, read_at=1000.0)
        self.status.save(budget)
        self.assertEqual(self.status.load(), budget)

    def test_the_file_carries_the_key_set_written_before_the_named_type(self):
        self.status.save(GithubBudget(limit=5000, remaining=1, reset=2.0, read_at=3.0))
        with open(self.path) as f:
            self.assertEqual(set(json.load(f)), {"limit", "remaining", "reset", "read_at"})

    def test_partial_numbers_load_as_none(self):
        self._write(json.dumps({"limit": 5000, "remaining": 1}))
        self.assertIsNone(self.status.load())

    def test_invalid_json_loads_as_none(self):
        self._write("{not json")
        self.assertIsNone(self.status.load())

    def test_a_json_list_loads_as_none(self):
        self._write("[1, 2]")
        self.assertIsNone(self.status.load())


if __name__ == "__main__":
    unittest.main()
