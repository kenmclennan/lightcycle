import unittest
from unittest import mock

from lightcycle.domain.work.worker_permissions import (
    WORKER_VERBS, worker_permitted, worker_refusal_message,
)


class TestWorkerPermitted(unittest.TestCase):
    def test_every_worker_verb_permitted_regardless_of_flags(self):
        for v in WORKER_VERBS:
            self.assertTrue(worker_permitted(v, {"title": "x"}), v)

    def test_every_forbidden_set_field_individually_forbids_set(self):
        for field in (
            "title", "description", "project", "workflow", "backlog", "label", "step", "unset",
        ):
            flags = {"state": "waiting", field: "x"}
            self.assertFalse(worker_permitted("set", flags), field)

    def test_set_with_state_waiting_and_no_forbidden_field_permitted(self):
        self.assertTrue(worker_permitted("set", {"state": "waiting"}))

    def test_set_with_non_waiting_state_forbidden(self):
        self.assertFalse(worker_permitted("set", {"state": "active"}))

    def test_set_with_no_state_key_forbidden(self):
        self.assertFalse(worker_permitted("set", {}))

    def test_a_verb_outside_worker_verbs_and_not_set_never_permitted(self):
        self.assertFalse(worker_permitted("rm", {"state": "waiting"}))


class TestWorkerRefusalMessage(unittest.TestCase):
    def test_message_lists_all_eight_verbs(self):
        self.assertIn(
            "claim, done, show, attach, retro, backlog, search, peek, set --state waiting",
            worker_refusal_message("rm"),
        )

    def test_message_is_derived_from_worker_verbs_not_a_separate_string(self):
        with mock.patch(
            "lightcycle.domain.work.worker_permissions.WORKER_VERBS", ("claim", "done")
        ):
            self.assertIn(
                "permitted: claim, done, set --state waiting", worker_refusal_message("rm")
            )


if __name__ == "__main__":
    unittest.main()
