import unittest

from lightcycle.application.flow.unblock_step import UnblockInput, UnblockStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.domain.feedback import LC_MARKER
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from lightcycle.ports.github import Comment, NotYetRead, ReadFailure
from tests.support.fake_github import FakeGitHub
from tests.support.fake_spin import FakeSpinPort
from tests.support.fake_store import FakeStore
from tests.support.stacked import layer_url as _layer_url


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

    def escalated_transition(self, transition, outcome, history, name=None, project=None):
        return self._flow.escalated_transition(transition, outcome, history, lambda key: None)

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
    disposition={"merged": "completed", "abandoned": "abandoned"},
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
        step = store.create_step(stage="build", role="agent", item=item)
        cc = CheckContentPinUseCase(store, github, _FlowAdapter(f), trusted_authors=lambda: frozenset({"review-code"}))
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

    def test_null_pin_on_an_attached_pr_pins_head_without_comparing_against_none(self):
        compared = []

        class _Recording(FakeGitHub):
            def changed_files(self, pr, sha):
                compared.append(sha)
                return super().changed_files(pr, sha)

        gh = _Recording(head_shas={self._URL: "sha1"})
        store, item, step, uc = self._setup(gh)

        uc.execute()

        self.assertEqual(self._pin(store, item), "sha1")
        self.assertEqual(compared, [])

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

    def test_regression_parks_the_step_of_the_prs_own_phase_not_an_earlier_open_step(self):
        flow = flow_from_metas(
            {
                "spec-fb": {
                    "step": "spec-feedback",
                    "phase": "spec",
                    "routes": {"done": "ready-merge"},
                },
                "reviewer": {
                    "step": "ready-merge",
                    "phase": "code",
                    "routes": {"merged": "cleanup"},
                    "on_pr_merge": "merged",
                },
            },
            disposition={"merged": "completed"},
        )
        gh = FakeGitHub(
            head_shas={self._URL: "sha1"},
            files_by_sha={(self._URL, "sha1"): frozenset({"a.py"})},
        )
        store = FakeStore()
        item = store.create_item("guarded feature", "a description")
        plant_pr(store, item, self._URL, phase="code")
        spec_step = store.create_step(stage="spec-feedback", role="agent", item=item)
        code_step = store.create_step(stage="ready-merge", role="human", item=item)
        cc = CheckContentPinUseCase(store, gh, _FlowAdapter(flow), trusted_authors=lambda: frozenset({"review-code"}))
        uc = _ContentPinRunner(store, cc, item, "code")
        uc.execute()

        gh._head_shas[self._URL] = "sha2"
        gh._files_by_sha[(self._URL, "sha2")] = frozenset()

        uc.execute()

        self.assertIn("a.py", store.get_node(code_step).notes)
        self.assertIsNone(store.get_node(spec_step).notes)
        self.assertEqual(store.get_node(spec_step).role, "agent")

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

        uc.execute()

        self.assertEqual(store.get_node(step).role, "human")
        self.assertNotIn("ci-pending", store.labels_of(step))

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
        step_9 = store.create_step(stage="build", role="agent", item=item,
            id="%s.9" % item)
        clock["now"] = "2026-01-01T00:00:01"
        step_10 = store.create_step(stage="build", role="agent", item=item,
            id="%s.10" % item)
        store.complete_node(step_9, "done")
        store.complete_node(step_10, "done")
        cc = CheckContentPinUseCase(store, gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
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
            body=LC_MARKER + "<!-- lc:decision=rework -->",
            is_top_level=False,
            path="b.py",
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
            body=LC_MARKER + "<!-- lc:decision=rework -->",
            is_top_level=False,
            path="ordered.py",
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

    def test_rework_decision_marker_authorizes_its_own_path(self):
        comment = Comment(
            author="review-code",
            body=LC_MARKER + "<!-- lc:decision=rework -->",
            is_top_level=False,
            path="b.py",
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

    def _forged_rework(self, author):
        comment = Comment(
            author=author,
            body=LC_MARKER + "<!-- lc:decision=rework -->",
            is_top_level=False,
            path="b.py",
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
        return store.get_node(step)

    def test_rework_marker_from_an_author_outside_trusted_authors_does_not_authorize_the_drop(self):
        node = self._forged_rework("colleague")

        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)

    def test_trusted_author_match_ignores_case(self):
        node = self._forged_rework("Review-Code")

        self.assertEqual(node.role, "agent")
        self.assertIsNone(node.notes)

    def test_marker_substring_naming_the_file_without_a_decision_no_longer_authorizes_it(self):
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

        self.assertEqual(store.get_node(step).role, "human")

    def test_answer_decision_marker_naming_the_file_does_not_authorize_it(self):
        comment = Comment(
            author="review-code",
            body=LC_MARKER + "<!-- lc:decision=answer -->" + " no need to touch b.py",
            is_top_level=False,
            path="b.py",
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



    def _round_decision(self, author, sha, with_decision=True):
        body = LC_MARKER + "<!-- lc:sha=%s -->" % sha
        if with_decision:
            body += "<!-- lc:decision=rework -->"
        comment = Comment(author=author, body=body, is_top_level=True, created_at=100.0)
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
        return store.get_node(step)

    def test_top_level_rework_decision_at_the_pinned_head_orders_the_drop_and_notes_it(self):
        node = self._round_decision("review-code", "sha1")

        self.assertEqual(node.role, "agent")
        self.assertIn("b.py", node.notes)
        self.assertIn("rework", node.notes)

    def test_top_level_rework_decision_naming_an_older_head_still_parks(self):
        node = self._round_decision("review-code", "sha0")

        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)

    def test_top_level_rework_decision_from_an_untrusted_author_still_parks(self):
        node = self._round_decision("colleague", "sha1")

        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)

    def test_no_decision_at_the_pinned_head_still_parks(self):
        node = self._round_decision("review-code", "sha1", with_decision=False)

        self.assertEqual(node.role, "human")
        self.assertIn("b.py", node.notes)


class TestContentPinOverAStack(unittest.TestCase):
    def _setup(self, signatures=None, files=None):
        import json
        from tests.support.stacked import STACK_URL, build_stack, head_shas_for

        self.json = json
        self.layers = build_stack(3)
        self.github = FakeGitHub(
            stacks={STACK_URL: self.layers}, head_shas=head_shas_for(self.layers),
            signatures=signatures or {}, files_by_sha=files or {})
        self.store = FakeStore()
        self.item = self.store.create_item("stacked", "a description")
        self.rid = plant_pr(self.store, self.item, self.layers[-1].url)
        self.store.set_stack(self.rid, STACK_URL)
        self.step = self.store.create_step(stage="build", role="agent", item=self.item)
        self.uc = CheckContentPinUseCase(
            self.store, self.github, _FlowAdapter(_FLOW),
            trusted_authors=lambda: frozenset({"review-code"}))

    def _run(self):
        self.uc.execute(self.store.get_node(self.item), self.layers[-1].url, None)

    def _pins(self):
        return self.json.loads(self.store.get_run(self.rid).content_pin)

    def test_per_layer_pins_are_recorded_as_a_json_map(self):
        self._setup()

        self._run()

        self.assertEqual(
            self._pins(), {_layer_url(n): "sha-%d" % n for n in (1, 2, 3)})

    def test_a_drop_on_layer_two_parks_naming_layer_two(self):
        two = _layer_url(2)
        self._setup(files={(two, "sha-2"): frozenset({"a.py", "b.py"}),
                           (two, "sha-2b"): frozenset({"a.py"})})
        self._run()
        self.github._head_shas[two] = "sha-2b"

        self._run()

        node = self.store.get_node(self.step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIn("layer 2 of 3 (%s)" % two, node.park.reason)
        self.assertEqual(self._pins()[two], "sha-2b")

    def test_a_cascaded_head_advances_the_pin_silently(self):
        two = _layer_url(2)
        self._setup(
            signatures={(two, "sha-2"): "same", (two, "sha-2b"): "same"},
            files={(two, "sha-2"): frozenset({"a.py", "lower.py"}),
                   (two, "sha-2b"): frozenset({"a.py"})})
        self._run()
        self.github._head_shas[two] = "sha-2b"

        self._run()

        self.assertIsNone(self.store.get_node(self.step).notes)
        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)
        self.assertEqual(self._pins()[two], "sha-2b")

    def test_an_old_plain_sha_pin_counts_as_no_pin(self):
        self._setup()
        self.store.set_content_pin(self.rid, "sha-3")

        self._run()

        self.assertEqual(
            self._pins(), {_layer_url(n): "sha-%d" % n for n in (1, 2, 3)})
        self.assertIsNone(self.store.get_node(self.step).notes)

    def test_an_unread_stack_leaves_the_pins_untouched(self):
        self._setup()
        self._run()
        before = self.store.get_run(self.rid).content_pin
        self.github._failing_calls = {"stack_view"}
        self.github._head_shas[_layer_url(2)] = "moved"

        self._run()

        self.assertEqual(self.store.get_run(self.rid).content_pin, before)

    def _move_layer_two(self, before, after, others=None, states=None):
        from tests.support.stacked import STACK_URL, build_stack

        one, two = _layer_url(1), _layer_url(2)
        files = {(two, "sha-2"): frozenset(before), (two, "sha-2b"): frozenset(after)}
        files.update(others or {})
        self._setup(files=files)
        if states:
            self.layers = build_stack(3, states=states)
            self.github.script_stack(STACK_URL, self.layers)
        self._run()
        self.github._head_shas[two] = "sha-2b"
        return one, two

    def test_a_file_moved_to_an_earlier_layer_parks_nothing(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py"}, {"a.py"}, {(_layer_url(1), "sha-1"): frozenset({"moved.py"})})

        self._run()

        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)
        self.assertEqual(self._pins()[two], "sha-2b")

    def test_a_file_moved_to_a_later_layer_parks_nothing(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py"}, {"a.py"}, {(_layer_url(3), "sha-3"): frozenset({"moved.py"})})

        self._run()

        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)
        self.assertEqual(self._pins()[two], "sha-2b")

    def test_files_moved_into_two_earlier_layers_park_nothing(self):
        from tests.support.stacked import STACK_URL, build_stack, head_shas_for

        layers = build_stack(4)
        urls = [_layer_url(n) for n in (1, 2, 3, 4)]
        files = {
            (urls[0], "sha-1"): frozenset({"x.py", "y.py"}),
            (urls[1], "sha-2"): frozenset({"p.py"}),
            (urls[2], "sha-3"): frozenset({"q.py", "r.py", "s.py"}),
            (urls[2], "sha-3b"): frozenset(),
            (urls[3], "sha-4"): frozenset({"t.py"}),
            (urls[3], "sha-4b"): frozenset(),
        }
        self._setup(files=files)
        self.layers = layers
        self.github.script_stack(STACK_URL, layers)
        self.github._head_shas = head_shas_for(layers)
        self._run()
        self.github._files_by_sha[(urls[0], "sha-1")] = frozenset({"x.py", "y.py"})
        self.github._files_by_sha[(urls[1], "sha-2")] = frozenset({"p.py", "q.py", "r.py"})
        self.github._files_by_sha[(urls[2], "sha-3b")] = frozenset({"s.py"})
        self.github._files_by_sha[(urls[3], "sha-4b")] = frozenset()
        self.github._head_shas[urls[2]] = "sha-3b"
        self.github._head_shas[urls[3]] = "sha-4b"
        self.github._files_by_sha[(urls[0], "sha-1")] = frozenset({"x.py", "y.py", "t.py"})

        self._run()

        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)

    def test_a_file_removed_from_every_layer_parks_naming_it_and_the_layer(self):
        one, two = self._move_layer_two({"a.py", "gone.py"}, {"a.py"})

        self._run()

        node = self.store.get_node(self.step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIn("layer 2 of 3 (%s)" % two, node.park.reason)
        self.assertIn("gone.py", node.park.reason)

    def test_a_mixed_recut_parks_naming_only_the_lost_file(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py", "gone.py"}, {"a.py"},
            {(_layer_url(1), "sha-1"): frozenset({"moved.py"})})

        self._run()

        node = self.store.get_node(self.step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIn("gone.py", node.park.reason)
        self.assertNotIn("moved.py", node.park.reason)

    def test_an_unreadable_other_layer_parks_nothing_and_keeps_the_pin(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py"}, {"a.py"}, {(_layer_url(1), "sha-1"): frozenset({"moved.py"})})
        real = self.github.changed_files
        failure = ReadFailure(1, "boom")
        self.github.changed_files = (
            lambda pr, sha, base=None: failure if pr == one else real(pr, sha, base))

        self._run()

        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)
        self.assertEqual(self._pins()[two], "sha-2")

    def test_a_not_yet_read_other_layer_keeps_the_pin(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py"}, {"a.py"}, {(_layer_url(1), "sha-1"): frozenset({"moved.py"})})
        real = self.github.head_sha
        self.github.head_sha = lambda pr: NotYetRead() if pr == one else real(pr)

        self._run()

        self.assertNotEqual(self.store.get_node(self.step).state, State.WAITING)
        self.assertEqual(self._pins()[two], "sha-2")

    def test_a_file_moved_into_a_merged_layer_is_still_reported_dropped(self):
        one, two = self._move_layer_two(
            {"a.py", "moved.py"}, {"a.py"}, {(_layer_url(1), "sha-1"): frozenset({"moved.py"})},
            states={1: "merged"})

        self._run()

        node = self.store.get_node(self.step)
        self.assertEqual(node.state, State.WAITING)
        self.assertIn("moved.py", node.park.reason)

    def test_a_rework_decision_at_the_pinned_head_notes_only_the_real_drop(self):
        one, two = _layer_url(1), _layer_url(2)
        self._setup(files={
            (two, "pin2"): frozenset({"a.py", "moved.py", "gone.py"}),
            (two, "sha-2b"): frozenset({"a.py"}),
            (one, "sha-1"): frozenset({"moved.py"})})
        self.github._head_shas[two] = "pin2"
        self._run()
        self.github._head_shas[two] = "sha-2b"
        self.github._timed_comments.append((100.0, Comment(
            author="review-code",
            body=LC_MARKER + "<!-- lc:sha=pin2 --><!-- lc:decision=rework -->",
            is_top_level=True,
            created_at=100.0)))

        self._run()

        node = self.store.get_node(self.step)
        self.assertNotEqual(node.state, State.WAITING)
        self.assertIn("ordered by the rework", node.notes)
        self.assertIn("gone.py", node.notes)
        self.assertNotIn("moved.py", node.notes)
        self.assertEqual(self._pins()[two], "sha-2b")


class TestContentPinUnstackedMakesNoLayerReads(unittest.TestCase):
    def test_a_single_pr_drop_parks_without_reading_other_layers(self):
        url = _layer_url(9)
        github = FakeGitHub(
            head_shas={url: "sha-a"},
            files_by_sha={(url, "sha-a"): frozenset({"a.py", "b.py"}),
                          (url, "sha-b"): frozenset({"a.py"})})
        store = FakeStore()
        item = store.create_item("single", "d")
        plant_pr(store, item, url)
        step = store.create_step(stage="build", role="agent", item=item)
        uc = CheckContentPinUseCase(
            store, github, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset())
        uc.execute(store.get_node(item), url, None)
        github._head_shas[url] = "sha-b"

        uc.execute(store.get_node(item), url, None)

        self.assertEqual(store.get_node(step).state, State.WAITING)
        self.assertNotIn("stack_view", [c[0] for c in github.calls])
