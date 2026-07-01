"""Real-bd wiring smoke: proves bd's actual output round-trips through our mappers
(bead_to_task / labels_for / status mapping). The FULL behavioural store contract
runs against FakeStore in unit (fast); here we only pay real bd for the core
mappings that a fake cannot vouch for.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

from the_grid.adapters.store import BdStore
from the_grid.application.work.status import StatusUseCase
from the_grid.config import Config

_TEMPLATE = None


def _template():
    """One real bd store inited per run; copied per test (real-bd fidelity without
    paying bd/Dolt init every time)."""
    global _TEMPLATE
    if _TEMPLATE is None:
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(
            ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
            cwd=d, check=True,
        )
        _TEMPLATE = d
    return _TEMPLATE


def _new_bd_root():
    d = tempfile.mkdtemp()
    shutil.copytree(_template(), d, dirs_exist_ok=True)
    return d


class TestBdStoreSmoke(unittest.TestCase):

    def setUp(self):
        self._root = _new_bd_root()
        self._prior = os.environ.get("GRID_ROOT_OVERRIDE")
        os.environ["GRID_ROOT_OVERRIDE"] = self._root

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("GRID_ROOT_OVERRIDE", None)
        else:
            os.environ["GRID_ROOT_OVERRIDE"] = self._prior

    def _store(self):
        return BdStore(Config())

    def test_create_task_roundtrips_structured_attrs(self):
        s = self._store()
        tid = s.create_task("build: x", step="build", role="coder", project="grid", goal="ship")
        t = s.get_task(tid)
        self.assertEqual((t.role, t.step, t.project, t.goal), ("coder", "build", "grid", "ship"))
        self.assertEqual(t.status, "ready")

    def test_claim_and_close_map_status(self):
        s = self._store()
        s.create_task("build: x", step="build", role="coder")
        claimed = s.claim_ready("coder")
        self.assertEqual(claimed.status, "in-progress")
        s.close(claimed.id, "done")
        self.assertEqual(s.get_task(claimed.id).status, "done")
        self.assertEqual(s.get_task(claimed.id).outcome, "done")

    def test_story_artifacts_roundtrip(self):
        s = self._store()
        sid = s.create_story("story: foo")
        s.add_artifact(sid, "spec", "specs/foo.md", "the spec")
        arts = s.story_artifacts(sid)
        self.assertEqual((arts[0].type, arts[0].value, arts[0].label),
                         ("spec", "specs/foo.md", "the spec"))

    def test_ready_reflects_deps_and_closes(self):
        s = self._store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        ready = [t.id for t in s.ready_tasks()]
        self.assertIn(blocker, ready)
        self.assertNotIn(blocked, ready)
        s.close(blocker, "done")
        self.assertIn(blocked, [t.id for t in s.ready_tasks()])

    def test_status_blocked_lane_reflects_open_blocker(self):
        s = self._store()
        blocker = s.create_task("blocker", role="coder")
        blocked = s.create_task("blocked", role="coder")
        s.dep_add(blocked, blocker)
        lanes = StatusUseCase(s).execute().lanes
        self.assertIn(blocked, [t.id for t in lanes["blocked"]])
        self.assertNotIn(blocked, [t.id for t in lanes["queue"]])
        self.assertIn(blocker, [t.id for t in lanes["queue"]])
        s.close(blocker, "done")
        lanes = StatusUseCase(s).execute().lanes
        self.assertIn(blocked, [t.id for t in lanes["queue"]])
        self.assertNotIn(blocked, [t.id for t in lanes["blocked"]])

    def test_route_to_human_relabels_and_notes(self):
        s = self._store()
        tid = s.create_task("build: x", step="build", role="coder")
        s.route_to_human(tid, "needs a human")
        t = s.get_task(tid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.status, "needs-human")
        self.assertIn("needs a human", t.notes or "")

    def test_tasks_closed_since_returns_closed_tasks_on_or_after_date(self):
        s = self._store()
        tid = s.create_task("build: x", step="build", role="coder")
        s.close(tid, "done")
        results = s.tasks_closed_since("2000-01-01")
        self.assertIn(tid, [t.id for t in results])

    def test_tasks_closed_since_excludes_open_tasks(self):
        s = self._store()
        s.create_task("open task", role="coder")
        results = s.tasks_closed_since("2000-01-01")
        self.assertEqual(results, [])

    def test_tasks_closed_since_excludes_stories(self):
        s = self._store()
        sid = s.create_story("closed story")
        s.close(sid, "merged")
        results = s.tasks_closed_since("2000-01-01")
        story_ids = [t.id for t in results]
        self.assertNotIn(sid, story_ids)

    def test_last_n_closed_epics_returns_top_level_closed_stories(self):
        s = self._store()
        epic1 = s.create_story("epic1")
        s.close(epic1, "merged")
        epic2 = s.create_story("epic2")
        s.close(epic2, "merged")
        results = s.last_n_closed_epics(1)
        self.assertEqual(len(results), 1)

    def test_last_n_closed_epics_excludes_open_stories(self):
        s = self._store()
        s.create_story("open epic")
        results = s.last_n_closed_epics(10)
        self.assertEqual(results, [])

    def test_last_n_closed_epics_excludes_nested_stories(self):
        s = self._store()
        epic = s.create_story("epic")
        child = s.create_story("child story", epic=epic)
        s.close(epic, "merged")
        s.close(child, "merged")
        results = s.last_n_closed_epics(10)
        result_ids = [t.id for t in results]
        self.assertIn(epic, result_ids)
        self.assertNotIn(child, result_ids)


if __name__ == "__main__":
    unittest.main()
