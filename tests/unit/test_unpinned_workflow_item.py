import time
import unittest

from lightcycle.application.flow.complete_step import CompleteStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.resolve_ci import ResolveCiUseCase
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
from lightcycle.application.services.flow import FlowService
from tests.support.fake_view_freshness import AlwaysConfirmed
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.schedule_fakes import StubWorkflowSource

_STANDARD = (
    "entry: write-code\n\n"
    "edges:\n"
    "  write-code   done    open-pr\n"
    "  open-pr      done    await-merge\n"
    "  await-merge  changes write-code\n\n"
    "hooks:\n"
    "  pr_merge   await-merge  merged\n"
    "  pr_close   await-merge  abandoned\n\n"
    "disposition:\n"
    "  merged     completed\n"
    "  abandoned  abandoned\n"
)

_GOOD_URL = "https://github.com/x/y/pull/1"
_BAD_URL = "https://github.com/x/y/pull/2"


class _NoWorktrees:
    def teardown_refusals(self, item, merged_prs=frozenset()):
        return []

    def release_run(self, run, delete_remote=True):
        pass

    def remove(self, item):
        pass


def _plant_pr(store, item, url):
    current = store.get_pass(store.open_pass(item))
    rid = store.open_run(item, current.id, None)
    store.set_branch(rid, "feat/x")
    store.set_pr(rid, url)


class TestUnpinnedWorkflowOnOneItem(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        source = StubWorkflowSource(workflows={"lc/standard": {}}, shas={"lc": "sha1"})
        self.flow = FlowService(
            FakeFs(metas={}, workflow={"standard": _STANDARD}), self.store,
            workflow_source=source,
        )
        self.good = self.store.create_item("good", "d", workflow="lc/standard@sha1")
        self.bad = self.store.create_item("bad", "d", workflow="lc/standard")
        self.store.create_step(step="await-merge", role="human", parent=self.good)
        self.bad_step = self.store.create_step(step="await-merge", role="human", parent=self.bad)
        _plant_pr(self.store, self.good, _GOOD_URL)
        _plant_pr(self.store, self.bad, _BAD_URL)

    def _complete(self):
        return CompleteStepUseCase(self.store, self.flow)

    def test_merge_monitor_processes_the_normal_item_and_notes_the_bad_one(self):
        github = FakeGitHub(merged_prs={_GOOD_URL, _BAD_URL})
        uc = ResolveMergedPrsUseCase(
            self.store, github, _NoWorktrees(), self.flow, self._complete(),
            CheckContentPinUseCase(
                self.store, github, self.flow, trusted_authors=lambda: frozenset()),
        )

        result = uc.execute()

        self.assertEqual(result.merged, [self.good])
        self.assertEqual(self.store.get_node(self.good).outcome, "merged")
        self.assertNotEqual(self.store.get_node(self.bad_step).state, "done")
        notes = self.store.get_node(self.bad_step).notes
        self.assertIn("workflow lc/standard is not a pin", notes)
        self.assertIn("lc set %s --workflow lc/standard" % self.bad, notes)

    def test_ci_monitor_notes_the_bad_item_and_does_not_raise(self):
        engine_step = self.store.create_step(step="await-merge", role="engine", parent=self.bad)
        uc = ResolveCiUseCase(self.store, FakeGitHub(), self.flow, self._complete(), clock=time.monotonic, poll_seconds=lambda: 60, ci_ceiling_seconds=lambda: 3600, wall_clock=lambda: 10000.0, views=AlwaysConfirmed())

        uc.execute()

        self.assertIn("is not a pin", self.store.get_node(engine_step).notes)

    def test_unpinned_workflow_names_only_stored_values_that_are_not_pins(self):
        self.assertEqual(self.flow.unpinned_workflow(self.store.get_node(self.bad)), "lc/standard")
        self.assertIsNone(self.flow.unpinned_workflow(self.store.get_node(self.good)))
