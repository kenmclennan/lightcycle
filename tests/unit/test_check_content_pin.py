import unittest

from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.release_ci_pending import CI_PENDING_LABEL
from lightcycle.domain.feedback import LC_MARKER
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from lightcycle.ports.github import Comment
from tests.support.fake_github import FakeGitHub
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore


def plant_pr(store, item, url, phase=None, branch=None, n=1, state="open"):
    while store.current_pass(item) is None or store.current_pass(item).n < n:
        current = store.current_pass(item)
        if current is not None:
            store.close_pass(current.id)
        store.open_pass(item)
    rid = store.open_run(item, store.current_pass(item).id, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, url)
    if state != "open":
        store.close_run(rid, state)
    return rid


class _FlowAdapter:
    def __init__(self, flow):
        self._flow = flow

    def workflow_for(self, step):
        return "wf"

    def project_for(self, step):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_for(self, node):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return sorted(self._flow.step_def(step).routes.keys())

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.step_def(step).owner

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.outcome if cap else None

    def ci_failed_cap_n(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.n if cap else None

    def ci_failed_cap_target(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.target if cap else None

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        }
    },
    disposition={"merged": "completed", "abandoned": "aborted"},
)


class _ContentPinRunner:
    def __init__(self, store, cc, item_id, phase):
        self._store = store
        self._cc = cc
        self._item_id = item_id
        self._phase = phase

    def execute(self):
        run = self._store.current_run(self._item_id, self._phase)
        pr_value = run.pr if run else None
        if pr_value is not None:
            self._cc.execute(self._store.get_node(self._item_id), pr_value, self._phase)


class TestMonitorPrsContentPin(unittest.TestCase):
    _URL = "https://github.com/x/y/pull/70"

    def _setup(self, github, flow=None):
        f = flow or _FLOW
        store = FakeStore()
        item = store.create_item("guarded feature", "a description")
        plant_pr(store, item, self._URL)
        step = store.create_step("build: guarded feature", step="build", role="agent", parent=item)
        cc = CheckContentPinUseCase(store, github)
        phase = f.step_def(f.merge_stages()[0]).phase
        uc = _ContentPinRunner(store, cc, item, phase)
        return store, item, step, uc

    def _pin(self, store, item):
        return next(r.content_pin for r in store.runs_of(item) if r.content_pin is not None)

    def test_first_observation_pins_without_escalating(self):
        gh = FakeGitHub(head_shas={self._URL: "sha1"})
        store, item, step, uc = self._setup(gh)

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha1")
        self.assertIsNone(store.get_node(step).notes)
        self.assertEqual(store.get_node(step).role, "agent")

    def test_head_sha_failure_never_pins_content_on_first_observation(self):
        gh = FakeGitHub(failing_calls={"head_sha"})
        store, item, step, uc = self._setup(gh)

        uc.execute()

        self.assertEqual(
            [r for r in store.runs_of(item) if r.content_pin is not None], []
        )

    def test_head_sha_failure_does_not_overwrite_an_established_pin(self):
        gh = FakeGitHub(head_shas={self._URL: "sha1"})
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._failing_calls = {"head_sha"}

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha1")

    def test_forward_progress_updates_pin_without_escalating(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset({"a.py", "b.py"})

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha2")
        self.assertIsNone(store.get_node(step).notes)
        self.assertEqual(store.get_node(step).role, "agent")

    def test_regression_routes_the_active_step_to_a_human(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"steps/a.md", "steps/b.md"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha2")
        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("sha1", node.park.reason)
        self.assertIn("sha2", node.park.reason)
        self.assertIn("steps/a.md", node.notes)
        self.assertIn("steps/b.md", node.notes)
        self.assertIn("steps/a.md", node.park.needs)
        self.assertIn("steps/b.md", node.park.needs)

    def test_pr_replaced_between_polls_does_not_report_the_old_prs_files_as_dropped(self):
        old_url = self._URL
        new_url = "https://github.com/x/y/pull/71"
        gh = FakeGitHub(
            head_shas={old_url: "sha1", new_url: "sha9"},
            files_by_sha={
                (old_url, "sha1"): frozenset({"a.py", "b.py"}),
                (new_url, "sha1"): frozenset({"a.py", "b.py"}),
                (new_url, "sha9"): frozenset({"c.py"}),
            },
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        store.record_pr_pin(store.current_run(item, None).id, new_url, None)
        uc.execute()

        self.assertEqual(self._pin(store, item), "sha9")
        self.assertIsNone(store.get_node(step).notes)
        self.assertEqual(store.get_node(step).role, "agent")

    def test_a_real_drop_on_the_new_pr_after_a_replacement_still_escalates(self):
        old_url = self._URL
        new_url = "https://github.com/x/y/pull/71"
        gh = FakeGitHub(
            head_shas={old_url: "sha1", new_url: "sha9"},
            files_by_sha={
                (old_url, "sha1"): frozenset({"a.py", "b.py"}),
                (new_url, "sha9"): frozenset({"c.py", "d.py"}),
            },
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        store.record_pr_pin(store.current_run(item, None).id, new_url, None)
        uc.execute()

        self.assertEqual(self._pin(store, item), "sha9")
        self.assertIsNone(store.get_node(step).notes)

        gh._head_shas[new_url] = "sha10"
        gh._files_by_sha[(new_url, "sha10")] = frozenset({"c.py"})

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha10")
        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("sha9", node.park.reason)
        self.assertIn("sha10", node.park.reason)
        self.assertIn("d.py", node.notes)
        self.assertIn("d.py", node.park.needs)

    def test_escalated_step_returns_to_its_lane_via_unblock(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        flow = flow_from_metas({
            "coder": {
                "model": "sonnet", "step": "build", "routes": {"done": "review"},
                "on_pr_merge": "done",
            },
        })
        store, item, step, uc = self._setup(gh, flow=flow)
        uc.execute()
        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertEqual(store.get_node(step).role, "human")

        resp = UnblockStepUseCase(
            store, _FlowAdapter(flow), spin_port=FakeSpinPort()
        ).execute(UnblockInput(step=step))

        self.assertEqual(resp.role, "agent")
        self.assertEqual(store.get_node(step).role, "agent")

    def test_drop_escalated_park_is_never_auto_released_by_ci(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        flow = flow_from_metas({
            "coder": {
                "model": "sonnet", "step": "build", "routes": {"done": "review"},
                "on_pr_merge": "done",
            },
        })
        store, item, step, uc = self._setup(gh, flow=flow)
        uc.execute()
        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()
        uc.execute()

        self.assertEqual(store.get_node(step).role, "human")

        gh._ci_pending_by_sha[(self._URL, "sha2")] = False

        uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertNotIn(CI_PENDING_LABEL, store.labels_of(step))

    def test_running_again_after_escalation_does_not_refire(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.md"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()
        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()
        uc.execute()
        notes_after_first_regression = store.get_node(step).notes

        uc.execute()

        self.assertEqual(store.get_node(step).notes, notes_after_first_regression)

    def test_mixed_change_escalates_naming_only_the_dropped_file(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"kept.py", "dropped.py"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset({"kept.py", "new.py"})

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("dropped.py", node.notes)
        self.assertNotIn("new.py", node.notes)

    def test_in_progress_step_is_not_reassigned_but_is_noted(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()
        store.assign(step, "worker1")
        store.update_state(step, State.RUNNING)

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.state, State.RUNNING)
        self.assertEqual(node.role, "agent")
        self.assertIn("a.py", store.get_node(step).notes)

    def test_no_active_step_notes_the_last_step(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()
        store.complete_node(step, "done")

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertIn("a.py", store.get_node(step).notes)

    def test_no_active_step_notes_the_most_recently_created_step_not_the_id_string_max(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        clock = {"now": "2026-01-01T00:00:00"}
        store = FakeStore(now=lambda: clock["now"])
        item = store.create_item("guarded feature", "a description")
        plant_pr(store, item, self._URL)
        step_9 = store.create_step(
            "build: guarded feature", step="build", role="agent", parent=item,
            id="%s.9" % item,
        )
        clock["now"] = "2026-01-01T00:00:01"
        step_10 = store.create_step(
            "build: guarded feature", step="build", role="agent", parent=item,
            id="%s.10" % item,
        )
        store.complete_node(step_9, "done")
        store.complete_node(step_10, "done")
        cc = CheckContentPinUseCase(store, gh)
        phase = _FLOW.step_def(_FLOW.merge_stages()[0]).phase
        uc = _ContentPinRunner(store, cc, item, phase)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertIsNone(store.get_node(step_9).notes)
        self.assertIn("a.py", store.get_node(step_10).notes)

    def test_unchanged_head_is_a_no_op(self):
        gh = FakeGitHub(head_shas={self._URL: "sha1"})
        store, item, step, uc = self._setup(gh)

        uc.execute()
        uc.execute()

        self.assertEqual(self._pin(store, item), "sha1")
        self.assertIsNone(store.get_node(step).notes)

    def test_changed_files_failure_declines_to_conclude_and_does_not_advance_the_pin(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()
        gh._failing_calls = {"changed_files"}

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha1")
        self.assertIsNone(store.get_node(step).notes)
        self.assertEqual(store.get_node(step).role, "agent")

    def test_removal_authorized_by_a_marked_comment_is_not_parked(self):
        comment = Comment(
            author="review-code",
            body=LC_MARKER + " Remove b.py - keep everything else.",
            is_top_level=True,
            created_at=100.0,
        )
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py", "b.py"})},
            timed_comments=[(100.0, comment)],
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset({"a.py"})

        uc.execute()

        self.assertEqual(store.get_node(step).role, "agent")
        self.assertIsNone(store.get_node(step).notes)
        self.assertEqual(self._pin(store, item), "sha2")

    def test_removal_without_a_marked_comment_still_parks(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"steps/a.md", "steps/b.md"})},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha2")
        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("sha1", node.park.reason)
        self.assertIn("sha2", node.park.reason)
        self.assertIn("steps/a.md", node.notes)
        self.assertIn("steps/b.md", node.notes)
        self.assertIn("steps/a.md", node.park.needs)
        self.assertIn("steps/b.md", node.park.needs)

    def test_mixed_drop_parks_naming_only_the_unauthorized_file(self):
        comment = Comment(
            author="review-code",
            body=LC_MARKER + " Remove ordered.py - keep everything else.",
            is_top_level=True,
            created_at=100.0,
        )
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={
                (self._URL, "sha1"): frozenset({"ordered.py", "stray.py"})
            },
            timed_comments=[(100.0, comment)],
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("stray.py", node.notes)
        self.assertNotIn("ordered.py", node.notes)
        self.assertIn("stray.py", node.park.needs)
        self.assertNotIn("ordered.py", node.park.needs)

    def test_unmarked_mention_of_the_dropped_file_does_not_authorize_it(self):
        comment = Comment(
            author="human",
            body="heads up, b.py looked off to me",
            is_top_level=True,
            created_at=100.0,
        )
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py", "b.py"})},
            timed_comments=[(100.0, comment)],
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset({"a.py"})

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)

    def test_thread_read_failure_fails_closed(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py", "b.py"})},
            failing_calls={"comments_since"},
        )
        store, item, step, uc = self._setup(gh)
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset({"a.py"})

        uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)
        self.assertIn("b.py", node.park.needs)
        self.assertIn("could not read", node.park.reason.lower())


