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
        self.assertEqual(t.state, "ready")

    def test_claim_and_close_map_status(self):
        s = self._store()
        s.create_step("build: x", step="build", role="coder")
        claimed = s.claim_ready("coder")
        self.assertEqual(claimed.state, "in_progress")
        s.close(claimed.id, "done")
        self.assertEqual(s.get_node(claimed.id).state, "done")
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
        self.assertEqual(t.state, "ready")
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

    def test_closed_unretroed_items_returns_closed_items(self):
        s = self._store()
        sid = s.create_item("closed item", theme=s.create_theme("theme"))
        s.close(sid, "merged")
        self.assertIn(sid, [t.id for t in s.closed_unretroed_items()])

    def test_closed_unretroed_items_excludes_open_and_retroed_and_origin(self):
        s = self._store()
        theme = s.create_theme("theme")
        s.create_item("open item", theme=theme)
        retroed = s.create_item("retroed item", theme=theme)
        s.close(retroed, "merged")
        s.label_add(retroed, "retroed")
        origin = s.create_item("origin item", theme=theme)
        s.close(origin, "merged")
        s.label_add(origin, "retro-origin")
        ids = [t.id for t in s.closed_unretroed_items()]
        self.assertNotIn(retroed, ids)
        self.assertNotIn(origin, ids)

    def test_last_n_closed_epics_returns_closed_epics(self):
        s = self._store()
        epic1 = s.create_theme("epic1")
        s.close(epic1, "merged")
        epic2 = s.create_theme("epic2")
        s.close(epic2, "merged")
        results = s.last_n_closed_themes(1)
        self.assertEqual(len(results), 1)

    def test_last_n_closed_epics_excludes_open_epics(self):
        s = self._store()
        s.create_theme("open theme")
        results = s.last_n_closed_themes(10)
        self.assertEqual(results, [])

    def test_last_n_closed_epics_excludes_nested_stories(self):
        s = self._store()
        theme = s.create_theme("theme")
        child = s.create_item("child item", theme=theme)
        s.close(theme, "merged")
        s.close(child, "merged")
        results = s.last_n_closed_themes(10)
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
        config = Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

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


_LEGACY_NODES_SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    step TEXT,
    role TEXT,
    parent TEXT,
    project TEXT,
    goal TEXT,
    description TEXT,
    notes TEXT,
    close_reason TEXT,
    assignee TEXT,
    since TEXT,
    fired_at TEXT,
    closed_at TEXT,
    created_at TEXT,
    attention INTEGER NOT NULL DEFAULT 0,
    theme TEXT,
    needs TEXT,
    model TEXT,
    workflow TEXT,
    state TEXT
);
CREATE TABLE deps (node_id TEXT NOT NULL, blocked_by TEXT NOT NULL);
CREATE TABLE artifacts (item_id TEXT NOT NULL, atype TEXT NOT NULL, value TEXT NOT NULL, label TEXT);
CREATE TABLE labels (node_id TEXT NOT NULL, label TEXT NOT NULL);
CREATE TABLE counters (namespace TEXT PRIMARY KEY, next INTEGER NOT NULL);
CREATE TABLE history (node_id TEXT NOT NULL, seq INTEGER NOT NULL, status TEXT NOT NULL, ts TEXT);
CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_tasks_status ON nodes(status);
CREATE INDEX idx_status_report ON nodes(role);
"""


class TestSqliteStoreStateCollapseMigration(unittest.TestCase):
    def _seed_legacy_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_LEGACY_NODES_SCHEMA)
        conn.executemany(
            "INSERT INTO nodes (id, type, status, role, assignee, state) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("s-closed", "step", "closed", "coder", None, None),
                ("s-active", "step", "in_progress", "coder", "sp1", None),
                ("s-ready", "step", "open", "coder", None, None),
                ("s-blocked", "step", "open", "coder", None, None),
                ("s-human", "step", "open", "human", None, None),
                ("i-todo", "item", "open", None, None, "todo"),
                ("i-active", "item", "open", None, None, "active"),
                ("i-5v5", "item", "closed", None, None, "todo"),
            ],
        )
        conn.execute(
            "INSERT INTO deps (node_id, blocked_by) VALUES ('s-blocked', 's-ready')"
        )
        conn.commit()
        conn.close()

    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def test_migration_maps_every_row_to_the_single_state_field(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        self.assertEqual(store.get_node("s-closed").state, "done")
        self.assertEqual(store.get_node("s-active").state, "in_progress")
        self.assertEqual(store.get_node("s-ready").state, "ready")
        self.assertEqual(store.get_node("s-blocked").state, "backlogged")
        self.assertEqual(store.get_node("s-human").state, "ready")
        self.assertEqual(store.get_node("i-todo").state, "backlogged")
        self.assertEqual(store.get_node("i-active").state, "backlogged")

        cols = {
            r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()
        }
        self.assertNotIn("status", cols)
        self.assertIn("state", cols)

    def test_closed_node_with_stale_legacy_state_reports_done(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        node = store.get_node("i-5v5")
        self.assertEqual(node.state, "done")

    def test_migration_backs_up_the_store_before_mutating_it(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        SqliteStore(self._config(root))

        backup = os.path.join(root, "backups", "store-pre-state-collapse.db.gz")
        self.assertTrue(os.path.exists(backup))

    def test_migration_drops_status_column_indexes_but_keeps_unrelated_ones(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        indexes = [
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'nodes'"
            ).fetchall()
        ]
        self.assertNotIn("idx_nodes_status", indexes)
        self.assertNotIn("idx_tasks_status", indexes)
        self.assertIn("idx_status_report", indexes)

    def test_migrated_step_is_claimable_once_its_blocker_closes(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        self.assertEqual(store.get_node("s-blocked").state, "backlogged")
        self.assertNotIn("s-blocked", [n.id for n in store.ready_steps()])

        store.close("s-ready", "done")

        self.assertEqual(store.get_node("s-blocked").state, "ready")
        self.assertIn("s-blocked", [n.id for n in store.ready_steps()])
        claimed = store.claim_ready("write-code")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.id, "s-blocked")


_PRE_OUTCOME_NODES_SCHEMA = """
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'ready',
    step TEXT,
    role TEXT,
    parent TEXT,
    project TEXT,
    goal TEXT,
    description TEXT,
    notes TEXT,
    close_reason TEXT,
    assignee TEXT,
    since TEXT,
    fired_at TEXT,
    closed_at TEXT,
    created_at TEXT,
    attention INTEGER NOT NULL DEFAULT 0,
    theme TEXT,
    needs TEXT,
    model TEXT,
    workflow TEXT
);
CREATE TABLE deps (node_id TEXT NOT NULL, blocked_by TEXT NOT NULL);
CREATE TABLE artifacts (item_id TEXT NOT NULL, atype TEXT NOT NULL, value TEXT NOT NULL, label TEXT);
CREATE TABLE labels (node_id TEXT NOT NULL, label TEXT NOT NULL);
CREATE TABLE counters (namespace TEXT PRIMARY KEY, next INTEGER NOT NULL);
CREATE TABLE history (node_id TEXT NOT NULL, seq INTEGER NOT NULL, state TEXT NOT NULL, ts TEXT);
"""


class TestSqliteStoreCloseReasonMigration(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _seed_legacy_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_PRE_OUTCOME_NODES_SCHEMA)
        conn.executemany(
            "INSERT INTO nodes (id, type, state, close_reason) VALUES (?, ?, ?, ?)",
            [
                ("i-merged", "item", "done", "merged"),
                ("s-done", "step", "done", "done"),
                ("s-open", "step", "ready", None),
            ],
        )
        conn.commit()
        conn.close()

    def test_legacy_close_reason_column_renamed_and_values_preserved(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertNotIn("close_reason", cols)
        self.assertIn("outcome", cols)

        self.assertEqual(store.get_node("i-merged").outcome, "merged")
        self.assertEqual(store.get_node("s-done").outcome, "done")
        self.assertIsNone(store.get_node("s-open").outcome)

    def test_migration_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertNotIn("close_reason", cols)
        self.assertIn("outcome", cols)
        self.assertEqual(store.get_node("i-merged").outcome, "merged")

    def test_fresh_store_has_outcome_and_not_close_reason(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertNotIn("close_reason", cols)
        self.assertIn("outcome", cols)


if __name__ == "__main__":
    unittest.main()
