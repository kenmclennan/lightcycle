import unittest

from lightcycle.cli import _worker_permitted
from lightcycle.config import Config


class TestWorkerPermitted(unittest.TestCase):
    def test_core_verbs_allowed(self):
        for v in ("claim", "done", "show", "attach"):
            self.assertTrue(_worker_permitted(v, ["ITEM.1"]), v)

    def test_retro_allowed_for_the_audit_worker(self):
        self.assertTrue(_worker_permitted("retro", ["--pending"]))

    def test_destructive_verbs_forbidden(self):
        for v in ("rm", "init", "new", "start", "sweep", "dep", "backlog", "config",
                  "workflow"):
            self.assertFalse(_worker_permitted(v, ["x"]), v)

    def test_set_state_blocked_allowed(self):
        self.assertTrue(_worker_permitted(
            "set", ["ITEM.1", "--state", "blocked", "--needs", "human", "--branch", "b"]))

    def test_set_state_blocked_equals_form_allowed(self):
        self.assertTrue(_worker_permitted("set", ["ITEM.1", "--state=blocked"]))

    def test_set_parent_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--parent", "THEME"]))

    def test_set_state_active_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--state", "active"]))

    def test_set_without_state_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--title", "x"]))

    def test_set_parent_alongside_blocked_still_forbidden(self):
        self.assertFalse(_worker_permitted("set", ["ITEM", "--state", "blocked", "--parent", "T"]))


class TestIsWorker(unittest.TestCase):
    def test_true_when_flag_set(self):
        self.assertTrue(Config(environ={"LC_WORKER": "1"}).is_worker())

    def test_false_when_absent(self):
        self.assertFalse(Config(environ={}).is_worker())


if __name__ == "__main__":
    unittest.main()
