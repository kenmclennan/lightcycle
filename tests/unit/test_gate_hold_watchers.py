import unittest

from lightcycle.application.work.gate_hold import GateHold
from lightcycle.application.work.release_gate import ReleaseGateInput, ReleaseGateUseCase
from lightcycle.domain.work import State
from tests.support.fake_github import FakeGitHub
from tests.support.stacked import build_stack
from tests.unit import test_resolve_merged_prs as merged
from tests.unit import test_update_behind_prs as behind


def _hold(store, step, note="leave it"):
    GateHold(store).place(step, note)


def _release(store, step):
    ReleaseGateUseCase(store).execute(ReleaseGateInput(target=step))


def _held_lines(store, step):
    return [l for l in (store.get_node(step).notes or "").splitlines() if l.startswith("held:")]


class TestResolveMergedPrsHeld(unittest.TestCase):
    def test_a_merged_pr_leaves_a_held_gate_open_and_notes_it_once(self):
        url = "https://github.com/x/y/pull/901"
        store, item, step, _, uc = merged.TestMonitorPrsMerged()._setup(
            url, FakeGitHub(merged_prs={url}))
        _hold(store, step)

        first = uc.execute()
        notes = store.get_node(step).notes
        uc.execute()

        self.assertEqual(first.merged, [])
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(store, step)],
            ["held: PR merged (would close the item)"])
        self.assertEqual(store.get_node(step).notes, notes)

    def test_release_lets_the_next_tick_apply_the_merge(self):
        url = "https://github.com/x/y/pull/902"
        store, item, step, _, uc = merged.TestMonitorPrsMerged()._setup(
            url, FakeGitHub(merged_prs={url}))
        _hold(store, step)
        uc.execute()

        _release(store, step)
        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(_held_lines(store, step), [])

    def test_a_closed_pr_leaves_a_held_gate_open(self):
        url = "https://github.com/x/y/pull/903"
        store, item, step, _, uc = merged.TestMonitorPrsClosedUnmerged()._setup(
            url, FakeGitHub(closed_prs={url}))
        _hold(store, step)

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(store, step)],
            ["held: PR closed without merging (would close the item)"])

    def test_release_lets_the_next_tick_apply_the_close(self):
        url = "https://github.com/x/y/pull/904"
        store, item, step, _, uc = merged.TestMonitorPrsClosedUnmerged()._setup(
            url, FakeGitHub(closed_prs={url}))
        _hold(store, step)
        uc.execute()

        _release(store, step)
        result = uc.execute()

        self.assertEqual(result.abandoned, [item])

    def test_an_engine_park_without_a_hold_does_not_stop_the_merge(self):
        url = "https://github.com/x/y/pull/905"
        store, item, step, _, uc = merged.TestMonitorPrsMerged()._setup(
            url, FakeGitHub(merged_prs={url}))
        store.update_metadata(step, {"reason": "r", "needs": "n", "tried": None})

        result = uc.execute()

        self.assertEqual(result.merged, [item])

    def test_an_engine_park_on_a_held_gate_still_blocks_the_merge(self):
        url = "https://github.com/x/y/pull/906"
        store, item, step, _, uc = merged.TestMonitorPrsMerged()._setup(
            url, FakeGitHub(merged_prs={url}))
        store.update_metadata(step, {"reason": "r", "needs": "n", "tried": None})
        _hold(store, step)

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(len(_held_lines(store, step)), 1)


class TestResolveMergedPrsHeldOverAStack(unittest.TestCase):
    def _rig(self):
        return merged.TestResolveMergedPrsOverAStack()._rig(
            build_stack(3, states={1: "merged", 2: "merged", 3: "merged"}))

    def test_a_merged_stack_on_a_held_gate_is_noted_once_and_left_unrecorded(self):
        store, item, step, _, uc = self._rig()
        _hold(store, step)

        first = uc.execute()
        notes = store.get_node(step).notes
        uc.execute()

        self.assertEqual(first.merged, [])
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertNotEqual(store.get_node(step).state, State.DONE)
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(store, step)],
            ["held: PR merged (would close the item)"])
        self.assertEqual(store.get_node(step).notes, notes)
        self.assertIsNone(store.current_run(item, None).stack_seen)

    def test_release_lets_the_next_tick_apply_the_stack_merge(self):
        store, item, step, _, uc = self._rig()
        _hold(store, step)
        uc.execute()

        _release(store, step)
        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(_held_lines(store, step), [])


_TWO_MERGE_GATES = (
    "entry: work-a\n\n"
    "requires: brief repo\n\n"
    "phase:\n"
    "  work-a   spec\n"
    "  gate-a   spec\n"
    "  work-b   code\n"
    "  gate-b   code\n\n"
    "nodes:\n"
    "  gate-a  await-merge\n"
    "  gate-b  await-merge\n"
    "  work-a  coder\n"
    "  work-b  coder\n\n"
    "edges:\n"
    "  gate-a  merged  work-b\n"
    "  gate-b  merged  work-a\n\n"
    "hooks:\n"
    "  pr_merge  gate-a  merged\n"
    "  pr_merge  gate-b  merged\n"
)


class TestResolveMergedPrsMixedGates(unittest.TestCase):
    def _setup(self):
        from lightcycle.application.flow import CompleteStepUseCase
        from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
        from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
        from lightcycle.domain.flow import Flow
        from lightcycle.domain.flow.graph import parse_graph
        from tests.support.fake_store import FakeStore
        from tests.support.null_collaborators import NoopWorktrees

        metas = {"await-merge": {"step": "await-merge"}, "coder": {"model": "sonnet"}}
        flow = Flow.from_graph(parse_graph(_TWO_MERGE_GATES), metas)
        store = FakeStore()
        item = store.create_item("two gates", "d")
        url_a = "https://github.com/x/y/pull/951"
        url_b = "https://github.com/x/y/pull/952"
        merged.plant_pr(store, item, url_a, "spec")
        merged.plant_pr(store, item, url_b, "code")
        gate_a = store.create_step(stage="gate-a", role="human", item=item)
        gate_b = store.create_step(stage="gate-b", role="human", item=item)
        github = FakeGitHub(merged_prs={url_a, url_b})
        adapter = merged._FlowAdapter(flow)
        uc = ResolveMergedPrsUseCase(
            store, github, merged.FakeWorktrees(), adapter,
            CompleteStepUseCase(store, adapter, worktrees=NoopWorktrees(), config=None),
            CheckContentPinUseCase(
                store, github, adapter, trusted_authors=lambda: frozenset({"review-code"})),
        )
        return store, item, gate_a, gate_b, uc

    def test_only_the_unheld_gate_completes_when_the_held_one_is_first(self):
        store, item, held, free, uc = self._setup()
        _hold(store, held)

        uc.execute()

        self.assertNotEqual(store.get_node(held).state, State.DONE)
        self.assertEqual(store.get_node(free).state, State.DONE)
        self.assertEqual(len(_held_lines(store, held)), 1)
        self.assertEqual(_held_lines(store, free), [])

    def test_only_the_unheld_gate_completes_when_the_held_one_is_second(self):
        store, item, free, held, uc = self._setup()
        _hold(store, held)

        uc.execute()

        self.assertNotEqual(store.get_node(held).state, State.DONE)
        self.assertEqual(store.get_node(free).state, State.DONE)
        self.assertEqual(len(_held_lines(store, held)), 1)
        self.assertEqual(_held_lines(store, free), [])


class TestBehindHeld(unittest.TestCase):
    def test_a_behind_pr_on_a_held_gate_is_not_updated_and_noted_once(self):
        github, url = behind._behind(941)
        h = behind._Harness(github)
        item, step = h.gate(url)
        _hold(h.store, step)

        h.uc.execute()
        notes = h.notes(step)
        h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(
            [l.split(" (x")[0] for l in _held_lines(h.store, step)],
            ["held: PR is behind the base branch "
             "(would update the branch through GitHub update-branch)"])
        self.assertEqual(h.notes(step), notes)

    def test_release_lets_the_next_tick_update_the_branch(self):
        github, url = behind._behind(942)
        h = behind._Harness(github)
        item, step = h.gate(url)
        _hold(h.store, step)
        h.uc.execute()

        _release(h.store, step)
        h.uc.execute()

        self.assertEqual(len(github.update_calls), 1)
        self.assertEqual(_held_lines(h.store, step), [])

    def test_a_held_gate_that_is_not_behind_notes_nothing(self):
        url = behind._pr(943)
        github = FakeGitHub(head_shas={url: "s"}, strict_bases={behind._BASE})
        h = behind._Harness(github)
        item, step = h.gate(url)
        _hold(h.store, step)

        h.uc.execute()

        self.assertEqual(h.notes(step), "")

    def test_two_gates_only_the_unheld_one_is_updated(self):
        github, url1 = behind._behind(944)
        url2 = behind._pr(945)
        github._behind.add(url2)
        github._head_shas[url2] = "sha2"
        h = behind._Harness(github)
        _, held_step = h.gate(url1)
        _, free_step = h.gate(url2)
        _hold(h.store, held_step)

        h.uc.execute()

        self.assertEqual([call[0] for call in github.update_calls], [url2])
        self.assertEqual(len(_held_lines(h.store, held_step)), 1)
        self.assertEqual(_held_lines(h.store, free_step), [])

    def test_a_held_gate_whose_read_failed_notes_nothing_and_writes_nothing(self):
        github, url = behind._behind(946, failing_calls={"pr_sync_state"})
        h = behind._Harness(github)
        item, step = h.gate(url)
        _hold(h.store, step)

        h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(h.notes(step), "")
        self.assertEqual(_held_lines(h.store, step), [])

    def test_a_held_gate_with_a_request_already_pending_notes_nothing(self):
        github, url = behind._behind(947)
        h = behind._Harness(github)
        item, step = h.gate(url)
        _hold(h.store, step)
        h.uc._pending[url] = ("sha1", behind._BASE)

        h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(h.notes(step), "")
        self.assertEqual(_held_lines(h.store, step), [])
        self.assertIn(url, h.uc._pending)
