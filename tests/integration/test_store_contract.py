import os
import shutil
import subprocess
import tempfile
import unittest

from the_grid.adapters.store import BdStore
from the_grid.application.work.status import StatusUseCase
from the_grid.config import Config
from tests.support.store_contract import StoreContractBase

_TEMPLATE = None


def _template():
    global _TEMPLATE
    if _TEMPLATE is None:
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(
            ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
            cwd=d,
            check=True,
        )
        _TEMPLATE = d
    return _TEMPLATE


def _new_bd_root():
    outer = tempfile.mkdtemp()
    d = os.path.join(outer, os.path.basename(_template()))
    shutil.copytree(_template(), d)
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
        self.assertEqual(
            (arts[0].type, arts[0].value, arts[0].label), ("spec", "specs/foo.md", "the spec")
        )

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

    def test_create_with_description_and_edit(self):
        s = self._store()
        tid = s.create_task("my task", description="initial desc")
        t = s.get_task(tid)
        self.assertEqual(t.description, "initial desc")
        s.edit_task(tid, title="updated title", description="updated desc")
        t2 = s.get_task(tid)
        self.assertEqual(t2.title, "updated title")
        self.assertEqual(t2.description, "updated desc")

    def test_edit_task_goal_and_project(self):
        s = self._store()
        tid = s.create_task("t", goal="g1", project="p1")
        s.edit_task(tid, goal="g2", project="p2")
        t = s.get_task(tid)
        self.assertEqual(t.goal, "g2")
        self.assertEqual(t.project, "p2")

    def test_edit_task_reparents(self):
        s = self._store()
        epic = s.create_story("epic")
        tid = s.create_task("a task")
        s.edit_task(tid, parent=epic)
        t = s.get_task(tid)
        self.assertEqual(t.parent, epic)

    def test_all_tasks_returns_beyond_default_bd_limit(self):
        s = self._store()
        created = [s.create_task(f"task {i}", role="coder") for i in range(51)]
        result_ids = {t.id for t in s.all_tasks()}
        for tid in created:
            self.assertIn(tid, result_ids)


class TestBdStoreContract(StoreContractBase, unittest.TestCase):
    def setUp(self):
        self._root = _new_bd_root()
        self._prior = os.environ.get("GRID_ROOT_OVERRIDE")
        os.environ["GRID_ROOT_OVERRIDE"] = self._root

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("GRID_ROOT_OVERRIDE", None)
        else:
            os.environ["GRID_ROOT_OVERRIDE"] = self._prior

    def make_store(self):
        return BdStore(Config())


class TestBdStoreIdSeam(unittest.TestCase):
    """Adapter-seam: ids above the port are short; both short and full ids are accepted."""

    def setUp(self):
        self._root = _new_bd_root()
        self._prefix = os.path.basename(self._root)
        self._prior = os.environ.get("GRID_ROOT_OVERRIDE")
        os.environ["GRID_ROOT_OVERRIDE"] = self._root

    def tearDown(self):
        if self._prior is None:
            os.environ.pop("GRID_ROOT_OVERRIDE", None)
        else:
            os.environ["GRID_ROOT_OVERRIDE"] = self._prior

    def _store(self):
        return BdStore(Config())

    def _is_short(self, tid):
        return tid is not None and not tid.startswith(self._prefix + "-")

    def test_task_id_is_short(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        self.assertTrue(self._is_short(tid), f"expected short id, got {tid!r}")

    def test_get_task_id_is_short(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        t = s.get_task(tid)
        self.assertTrue(self._is_short(t.id), f"task.id not short: {t.id!r}")

    def test_get_task_accepts_full_id(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        full_id = self._prefix + "-" + tid
        t = s.get_task(full_id)
        self.assertEqual(t.id, tid)

    def test_parent_is_short(self):
        s = self._store()
        sid = s.create_story("story")
        tid = s.create_task("t", role="coder", parent=sid)
        t = s.get_task(tid)
        self.assertTrue(self._is_short(t.parent), f"task.parent not short: {t.parent!r}")
        self.assertEqual(t.parent, sid)

    def test_story_children_ids_are_short(self):
        s = self._store()
        sid = s.create_story("story")
        tid = s.create_task("t", role="coder", parent=sid)
        kids = s.children(sid)
        self.assertEqual(len(kids), 1)
        self.assertTrue(self._is_short(kids[0].id), f"child id not short: {kids[0].id!r}")
        self.assertEqual(kids[0].id, tid)

    def test_closed_stories_id_is_short(self):
        s = self._store()
        sid = s.create_story("closed story")
        s.close(sid, "done")
        closed = s.closed_stories()
        self.assertEqual(len(closed), 1)
        self.assertTrue(self._is_short(closed[0]["id"]), f"closed story id not short: {closed[0]['id']!r}")
        self.assertEqual(closed[0]["id"], sid)

    def test_all_tasks_ids_are_short(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        tasks = s.all_tasks()
        ids = [t.id for t in tasks]
        self.assertIn(tid, ids)
        for i in ids:
            self.assertTrue(self._is_short(i), f"id not short: {i!r}")

    def test_story_id_is_short(self):
        s = self._store()
        sid = s.create_story("s")
        self.assertTrue(self._is_short(sid), f"story id not short: {sid!r}")

    def test_close_with_short_id_works(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        s.close(tid, "done")
        self.assertEqual(s.get_task(tid).status, "done")

    def test_close_with_full_id_works(self):
        s = self._store()
        tid = s.create_task("t", role="coder")
        full_id = self._prefix + "-" + tid
        s.close(full_id, "done")
        self.assertEqual(s.get_task(tid).status, "done")


if __name__ == "__main__":
    unittest.main()
