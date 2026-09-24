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


class TestWorkerPermittedAttach(unittest.TestCase):
    def test_attach_repo_forbidden(self):
        self.assertFalse(worker_permitted("attach", {"type": "repo"}))

    def test_attach_of_every_step_used_type_permitted(self):
        for t in (
            "spec", "spec-amendment", "comments-handled", "checks-run", "pr", "branch", "reflection",
        ):
            self.assertTrue(worker_permitted("attach", {"type": t}), t)

    def test_attach_without_a_type_key_permitted(self):
        self.assertTrue(worker_permitted("attach", {}))

    def test_attach_type_comparison_is_exact(self):
        self.assertTrue(worker_permitted("attach", {"type": "Repo"}))


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

    def test_attach_message_names_the_forbidden_type_and_says_attach_is_otherwise_permitted(self):
        msg = worker_refusal_message("attach")
        self.assertIn("type repo", msg)
        self.assertIn("attach is otherwise permitted", msg)

    def test_attach_message_is_derived_from_the_forbidden_type_tuple(self):
        with mock.patch(
            "lightcycle.domain.work.worker_permissions._ATTACH_FORBIDDEN_TYPES", ("repo", "resolves")
        ):
            self.assertIn("type repo, resolves", worker_refusal_message("attach"))

    def test_message_for_other_verbs_is_unchanged_by_the_forbidden_type_tuple(self):
        with mock.patch(
            "lightcycle.domain.work.worker_permissions._ATTACH_FORBIDDEN_TYPES", ("repo", "resolves")
        ):
            self.assertNotIn("resolves", worker_refusal_message("rm"))


if __name__ == "__main__":
    unittest.main()
