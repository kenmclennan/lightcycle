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


if __name__ == "__main__":
    unittest.main()
