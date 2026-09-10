import unittest

from lightcycle.application.flow import BlockInput, BlockStepUseCase
from lightcycle.application.pool.release_ci_pending import ReleaseCiPendingUseCase
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
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
        return self._flow.outcomes_for(step)

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.owner_of(step)

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_outcome(step)

    def ci_failed_cap_n(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_n(step)

    def ci_failed_cap_target(self, step, name=None, project=None):
        return self._flow.ci_failed_cap_target(step)

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return self._flow.phase_of(getattr(node, "step", None))

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


class FakeConfig:
    def ci_release_cap(self):
        return 3


_CI_PENDING_FLOW = flow_from_metas({
    "review-features": {
        "model": "sonnet",
        "step": "review-features",
        "routes": {"done": "await-merge"},
    },
})


class TestMonitorPrsCiPendingRelease(unittest.TestCase):
    _URL = "https://github.com/x/y/pull/90"

    def _setup(self, github):
        store = FakeStore()
        item = store.create_item("reviewed feature", "a description")
        plant_pr(store, item, self._URL)
        step = store.create_step(
            "review-features: reviewed feature", step="review-features", role="human",
            parent=item,
        )
        spin_port = FakeSpinPort({"steps": {step: {"count": 2, "since": 0, "last_line": "x"}}})
        uc = ReleaseCiPendingUseCase(
            store, github, _FlowAdapter(_CI_PENDING_FLOW), spin_port, FakeConfig()
        )
        return store, item, step, uc, spin_port

    def _label_and_park(self, store, step, reason="something odd", needs="confirm CI"):
        store.label_add(step, "ci-pending")
        BlockStepUseCase(store).execute(BlockInput(step=step, needs=needs, reason=reason))

    def test_ci_concluded_release_clears_the_steps_spin_entry(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        uc.execute()

        self.assertIsNone(spin_port.load().entry(step))

    def test_ci_still_pending_does_not_release(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): True}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])

    def test_ci_concluded_releases_exactly_once(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        result = uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "agent")
        self.assertEqual(node.state, State.QUEUED)
        self.assertEqual(result.released, [item])
        self.assertIn("ci-released:1", store.labels_of(step))

    def test_release_clears_the_label_so_a_later_unrelated_park_is_not_auto_released(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        uc.execute()
        self.assertNotIn("ci-pending", store.labels_of(step))

        BlockStepUseCase(store).execute(
            BlockInput(step=step, needs="confirm scenarios", reason="cannot review the scenarios")
        )

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])

    def test_a_failing_final_label_add_leaves_the_unblock_and_label_remove_unapplied(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        original_label_add = store.label_add

        def raising_label_add(tid, label):
            if label.startswith("ci-released:"):
                raise RuntimeError("boom")
            return original_label_add(tid, label)

        store.label_add = raising_label_add
        with self.assertRaises(RuntimeError):
            uc.execute()

        node = store.get_node(step)
        self.assertEqual(node.role, "human")
        self.assertIn("ci-pending", store.labels_of(step))
        self.assertNotIn("ci-released:1", store.labels_of(step))

    def test_finding_survives_automatic_release(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step, reason="something odd", needs="confirm CI")

        uc.execute()

        self.assertIn(
            "PARK RESOLVED: reason=something odd | needs=confirm CI",
            store.get_node(step).notes,
        )

    def test_read_failure_never_releases(self):
        gh = FakeGitHub(head_shas={self._URL: "sha1"}, failing_calls={"ci_pending"})
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])
        self.assertNotIn("ci-released:1", store.labels_of(step))

    def test_empty_head_sha_never_releases(self):
        gh = FakeGitHub()
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])

    def test_head_sha_read_failure_never_releases(self):
        gh = FakeGitHub(head_shas={self._URL: "sha1"}, failing_calls={"head_sha"})
        store, item, step, uc, spin_port = self._setup(gh)
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])
        self.assertNotIn("ci-released:1", store.labels_of(step))

    def test_park_without_the_label_is_never_released(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        BlockStepUseCase(store).execute(
            BlockInput(step=step, needs="confirm CI", reason="waiting")
        )

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])

    def test_prose_mentioning_ci_pending_is_never_released_without_the_label(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        BlockStepUseCase(store).execute(BlockInput(
            step=step, needs="check CI pending state",
            reason="waiting on CI, pending forever it seems",
        ))

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertEqual(result.released, [])

    def test_cap_leaves_a_fourth_park_for_a_human(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        for _ in range(3):
            self._label_and_park(store, step)
            uc.execute()
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertNotIn(item, result.released)
        self.assertNotIn("ci-released:4", store.labels_of(step))
        self.assertIn("automatic release cap", store.get_node(step).notes)

    def test_cap_is_read_fresh_from_labels_not_tracked_across_calls(self):
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"}, ci_pending_by_sha={(self._URL, "sha1"): False}
        )
        store, item, step, uc, spin_port = self._setup(gh)
        store.label_add(step, "ci-released:1")
        store.label_add(step, "ci-released:2")
        self._label_and_park(store, step)

        result = uc.execute()

        self.assertIn(item, result.released)
        self.assertIn("ci-released:3", store.labels_of(step))


