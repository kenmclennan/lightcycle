import os
import sqlite3
import tempfile
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.store_contract import StoreContractBase
from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.application.work.status import StatusUseCase
from lightcycle.config import Config


class TestSqliteStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self, now=None):
        return make_sqlite_store(now=now)


class TestSqliteStoreRoundtrips(unittest.TestCase):
    def _store(self):
        return make_sqlite_store()

    def test_create_task_roundtrips_structured_attrs(self):
        s = self._store()
        tid = s.create_step("build: x", step="build", role="coder", project="grid", goal="ship")
        t = s.get_node(tid)
        self.assertEqual((t.role, t.step, t.project, t.goal), ("coder", "build", "grid", "ship"))
        self.assertEqual(t.status, "ready")

    def test_claim_and_close_map_status(self):
        s = self._store()
        s.create_step("build: x", step="build", role="coder")
        claimed = s.claim_ready("coder")
        self.assertEqual(claimed.status, "in-progress")
        s.close(claimed.id, "done")
        self.assertEqual(s.get_node(claimed.id).status, "done")
        self.assertEqual(s.get_node(claimed.id).outcome, "done")

    def test_story_artifacts_roundtrip(self):
        s = self._store()
        sid = s.create_item("item: foo", theme=s.create_theme("theme"))
        s.add_artifact(sid, "spec", "specs/foo.md", "the spec")
        arts = s.item_artifacts(sid)
        self.assertEqual(
            (arts[0].type, arts[0].value, arts[0].label), ("spec", "specs/foo.md", "the spec")
        )

    def test_ready_reflects_deps_and_closes(self):
        s = self._store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
        s.dep_add(blocked, blocker)
        ready = [t.id for t in s.ready_steps()]
        self.assertIn(blocker, ready)
        self.assertNotIn(blocked, ready)
        s.close(blocker, "done")
        self.assertIn(blocked, [t.id for t in s.ready_steps()])

    def test_status_blocked_lane_reflects_open_blocker(self):
        s = self._store()
        blocker = s.create_step("blocker", role="coder")
        blocked = s.create_step("blocked", role="coder")
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
        tid = s.create_step("build: x", step="build", role="coder")
        s.route_to_human(tid, "needs a human")
        t = s.get_node(tid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.status, "needs-human")
        self.assertIn("needs a human", t.notes or "")

    def test_tasks_closed_since_returns_closed_tasks_on_or_after_date(self):
        s = self._store()
        tid = s.create_step("build: x", step="build", role="coder")
        s.close(tid, "done")
        results = s.nodes_closed_since("2000-01-01")
        self.assertIn(tid, [t.id for t in results])

    def test_tasks_closed_since_excludes_open_tasks(self):
        s = self._store()
        s.create_step("open step", role="coder")
        results = s.nodes_closed_since("2000-01-01")
        self.assertEqual(results, [])

    def test_tasks_closed_since_excludes_stories(self):
        s = self._store()
        sid = s.create_item("closed item", theme=s.create_theme("theme"))
        s.close(sid, "merged")
        results = s.nodes_closed_since("2000-01-01")
        self.assertNotIn(sid, [t.id for t in results])

    def test_last_n_closed_epics_returns_closed_epics(self):
        s = self._store()
        epic1 = s.create_theme("epic1")
        s.close(epic1, "merged")
        epic2 = s.create_theme("epic2")
        s.close(epic2, "merged")
        results = s.last_n_closed_epics(1)
        self.assertEqual(len(results), 1)

    def test_last_n_closed_epics_excludes_open_epics(self):
        s = self._store()
        s.create_theme("open theme")
        results = s.last_n_closed_epics(10)
        self.assertEqual(results, [])

    def test_last_n_closed_epics_excludes_nested_stories(self):
        s = self._store()
        theme = s.create_theme("theme")
        child = s.create_item("child item", theme=theme)
        s.close(theme, "merged")
        s.close(child, "merged")
        results = s.last_n_closed_epics(10)
        result_ids = [t.id for t in results]
        self.assertIn(theme, result_ids)
        self.assertNotIn(child, result_ids)

    def test_all_tasks_returns_many(self):
        s = self._store()
        created = [s.create_step("step %d" % i, role="coder") for i in range(51)]
        result_ids = {t.id for t in s.all_nodes()}
        for tid in created:
            self.assertIn(tid, result_ids)


class TestSqliteStoreHistoryMigration(unittest.TestCase):
    def test_legacy_history_rows_without_ts_column_read_back_as_unknown(self):
        root = tempfile.mkdtemp()
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        config = Config(environ={"LC_ROOT_OVERRIDE": root, "LC_CONFIG": cfg_path})

        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.execute(
            "CREATE TABLE history (node_id TEXT NOT NULL, seq INTEGER NOT NULL, "
            "status TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO history (node_id, seq, status) VALUES ('legacy-1', 0, 'in-progress')"
        )
        conn.commit()
        conn.close()

        store = SqliteStore(config)
        self.assertEqual(store.history("legacy-1"), [("in-progress", None)])


if __name__ == "__main__":
    unittest.main()
