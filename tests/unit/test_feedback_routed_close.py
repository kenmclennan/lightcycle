import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore
from tests.unit.test_atomic_completion import StubWorktrees

GRAPH = """
entry: await-merge

edges:
  await-merge   changes  rework-stage
  rework-stage  done
  fb            done
  fb            rework

hooks:
  pr_feedback        await-merge  fb
  pr_feedback_route  fb  rework  changes
"""

METAS = {
    "await-merge": {"step": "await-merge"},
    "fb": {"model": "sonnet", "step": "fb"},
    "rework-stage": {"model": "sonnet", "step": "rework-stage"},
}


class WatchedCloseFault(FakeStore):
    fail_for = None

    def complete_step_atomic(self, tid, outcome, expected_assignee, next_step_spec):
        if tid == self.fail_for:
            raise RuntimeError("killed")
        return super().complete_step_atomic(tid, outcome, expected_assignee, next_step_spec)


def flow_service(store, graph=GRAPH):
    return FlowService(FakeFs(METAS, workflow=graph), store)


def world(store=None, watched=True):
    store = store or FakeStore()
    item = store.create_item("story", "a description")
    gate = store.create_step(stage="await-merge", role="human", item=item)
    store.update_state(gate, State.WAITING)
    fb = store.create_step(stage="fb", role="agent", item=item)
    store.update_state(fb, State.RUNNING)
    store.assign(fb, "sp-1")
    if watched:
        store.set_watched_step(fb, gate)
    return store, item, gate, fb


def close(store, step, outcome, note=None):
    uc = CompleteStepUseCase(store, flow_service(store), StubWorktrees(), config=None)
    return uc.execute(CompleteInput(step=step, outcome=outcome, note=note))


def outcome_notes(store, step):
    return [n for n in (store.get_node(step).notes or "").splitlines() if n.startswith("outcome:")]


def steps_at(store, stage):
    return [n for n in store.all_nodes() if n.type == "step" and n.stage == stage]


class TestRoutedClose(unittest.TestCase):
    def test_rework_close_closes_watched_with_changes_and_note(self):
        store, item, gate, fb = world()
        self.assertEqual(store.get_node(gate).state, State.WAITING)
        self.assertEqual(store.get_node(fb).state, State.RUNNING)

        close(store, fb, "rework", "fix the thing")

        watched = store.get_node(gate)
        self.assertEqual(watched.state, State.DONE)
        self.assertEqual(watched.outcome, "changes")
        self.assertEqual(watched.report, "fix the thing")
        self.assertEqual(len(steps_at(store, "rework-stage")), 1)
        own = store.get_node(fb)
        self.assertEqual(own.state, State.DONE)
        self.assertEqual(own.outcome, "rework")
        self.assertEqual(own.report, "fix the thing")

    def test_plain_done_leaves_watched_waiting(self):
        store, item, gate, fb = world()
        self.assertEqual(store.get_node(gate).state, State.WAITING)

        close(store, fb, "done", "nothing to change")

        self.assertEqual(store.get_node(gate).state, State.WAITING)
        self.assertEqual(steps_at(store, "rework-stage"), [])
        self.assertEqual(store.get_node(fb).state, State.DONE)

    def test_watched_close_failure_stores_nothing(self):
        store = WatchedCloseFault()
        store, item, gate, fb = world(store)
        store.fail_for = gate
        before = len(store.all_nodes())

        with self.assertRaises(RuntimeError):
            close(store, fb, "rework", "fix the thing")

        self.assertEqual(store.get_node(fb).state, State.RUNNING)
        self.assertEqual(store.get_node(gate).state, State.WAITING)
        self.assertEqual(outcome_notes(store, fb), [])
        self.assertEqual(outcome_notes(store, gate), [])
        self.assertEqual(len(store.all_nodes()), before)

    def test_watched_already_done_refuses_rework_close(self):
        store, item, gate, fb = world()
        store.complete_step_atomic(gate, "merged", None, None)
        self.assertEqual(store.get_node(gate).state, State.DONE)

        with self.assertRaises(UseCaseError) as caught:
            close(store, fb, "rework", "fix the thing")

        self.assertIn(gate, str(caught.exception))
        self.assertIn("done", str(caught.exception))
        self.assertEqual(store.get_node(fb).state, State.RUNNING)

    def test_no_watched_step_refuses_rework_close(self):
        store, item, gate, fb = world(watched=False)

        with self.assertRaises(UseCaseError):
            close(store, fb, "rework", "fix the thing")

        self.assertEqual(store.get_node(fb).state, State.RUNNING)
        self.assertEqual(store.get_node(gate).state, State.WAITING)
        self.assertEqual(outcome_notes(store, fb), [])


if __name__ == "__main__":
    unittest.main()
