import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import lightcycle.cli as cli
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.store_contract import StoreContractBase
from lightcycle.adapters.sqlite_store import SchemaVersionRefused, SqliteStore, _SCHEMA_VERSION
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.status import StatusUseCase
from lightcycle.config import Config
from lightcycle.container import Container


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

    def test_edit_node_reids_a_referenceless_item_into_the_new_parents_namespace(self):
        s = self._store()
        theme = s.create_theme("theme")
        standalone = s.create_item("standalone")
        new_id = s.edit_node(standalone, parent=theme)
        sibling = s.create_item("sibling", theme=theme)
        self.assertEqual(new_id, "%s.1" % theme)
        self.assertEqual(sibling, "%s.2" % theme)
        self.assertEqual(s.get_node(new_id).parent, theme)
        with self.assertRaises(KeyError):
            s.get_node(standalone)

    def test_edit_node_keeps_id_when_item_has_a_child_step(self):
        s = self._store()
        theme = s.create_theme("theme")
        item = s.create_item("has a step")
        s.create_step("child", parent=item)
        new_id = s.edit_node(item, parent=theme)
        self.assertEqual(new_id, item)
        self.assertEqual(s.get_node(item).parent, theme)

    def test_edit_node_keeps_id_for_each_id_bearing_artifact_type(self):
        s = self._store()
        theme = s.create_theme("theme")
        for atype in ("branch", "pr", "spec", "resolves", "filed-from", "brief"):
            item = s.create_item("item %s" % atype)
            s.add_artifact(item, atype, "value")
            new_id = s.edit_node(item, parent=theme)
            self.assertEqual(new_id, item)

    def test_edit_node_still_reids_with_only_a_non_id_bearing_artifact(self):
        s = self._store()
        theme = s.create_theme("theme")
        item = s.create_item("has a repo")
        s.add_artifact(item, "repo", "saga")
        new_id = s.edit_node(item, parent=theme)
        self.assertEqual(new_id, "%s.1" % theme)

    def test_edit_node_reid_repoints_deps_and_removes_the_old_id_everywhere(self):
        s = self._store()
        theme = s.create_theme("theme")
        blocker = s.create_step("blocker")
        item = s.create_item("blocked item")
        s.dep_add(item, blocker)
        s.dep_add(blocker, item)
        s.label_add(item, "retro-origin")
        s.update_state(item, "in_progress")

        new_id = s.edit_node(item, parent=theme)

        deps = set(
            s._conn.execute("SELECT node_id, blocked_by FROM deps").fetchall()
        )
        self.assertIn((new_id, blocker), deps)
        self.assertIn((blocker, new_id), deps)
        self.assertNotIn(item, [row[0] for row in deps] + [row[1] for row in deps])

        self.assertEqual(
            s._conn.execute("SELECT COUNT(*) FROM nodes WHERE id = ?", (item,)).fetchone()[0], 0
        )
        self.assertEqual(
            s._conn.execute(
                "SELECT COUNT(*) FROM history WHERE node_id = ?", (item,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            s._conn.execute(
                "SELECT COUNT(*) FROM labels WHERE node_id = ?", (item,)
            ).fetchone()[0],
            0,
        )
        new_labels = [
            row[0] for row in s._conn.execute(
                "SELECT label FROM labels WHERE node_id = ?", (new_id,)
            ).fetchall()
        ]
        self.assertIn("retro-origin", new_labels)

    def test_edit_node_parent_move_to_own_current_parent_is_a_no_op(self):
        s = self._store()
        theme = s.create_theme("theme")
        item = s.create_item("already here", theme=theme)
        new_id = s.edit_node(item, parent=theme)
        self.assertEqual(new_id, item)

    def test_activate_item_use_case_threads_the_reidded_item_through_file_step(self):
        s = self._store()
        metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
        workflow = graph_text_from_metas(metas, entry="build")
        flow = FlowService(FakeFs(metas, workflow=workflow), s)

        theme = s.create_theme("payments")
        item = s.create_item("add refunds")
        resp = ActivateItemUseCase(s, flow, None, None).execute(
            ActivateItemInput(item=item, workflow="standard", theme=theme)
        )

        new_item_id = "%s.1" % theme
        with self.assertRaises(KeyError):
            s.get_node(item)
        self.assertEqual(s.get_node(new_item_id).state, "ready")
        self.assertEqual(s.get_node(resp.step).parent, new_item_id)

    def test_cmd_set_parent_and_backlog_links_the_resolved_backlog_to_the_reidded_item(self):
        s = self._store()
        cli.set_container(Container(store=s))
        theme = s.create_theme("theme")
        backlog_item = s.create_item("a backlog todo")
        item = s.create_item("adopt me")

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_set([item, "--parent", theme, "--backlog", backlog_item]) or 0
        self.assertEqual(rc, 0, err.getvalue())

        new_id = "%s.1" % theme
        self.assertEqual(out.getvalue().strip(), new_id)
        arts = s.item_artifacts(new_id)
        self.assertTrue(
            any(a.type == "resolves" and a.value == backlog_item for a in arts)
        )
        with self.assertRaises(KeyError):
            s.get_node(item)


class TestSqliteStoreSchemaVersionFloor(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def test_fresh_store_is_stamped_current_and_usable(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))

        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, _SCHEMA_VERSION)

        tid = store.create_step("write-code: x", role="write-code")
        self.assertEqual(store.get_node(tid).title, "write-code: x")

    def test_unstamped_current_store_is_retro_stamped_with_data_intact(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        tid = store.create_step("write-code: x", role="write-code")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        reopened = SqliteStore(self._config(root))

        version = reopened._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, _SCHEMA_VERSION)
        self.assertEqual(reopened.get_node(tid).title, "write-code: x")

    def test_reopening_a_stamped_store_does_not_churn(self):
        root = tempfile.mkdtemp()
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, _SCHEMA_VERSION)

    def test_store_with_status_column_present_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("ALTER TABLE nodes ADD COLUMN status TEXT")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))
        self.assertIn("0.2.27", str(cm.exception))

        conn = sqlite3.connect(os.path.join(root, "store.db"))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertIn("status", cols)

    def test_store_missing_workflow_column_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("ALTER TABLE nodes DROP COLUMN workflow")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_history_status_without_state_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("ALTER TABLE history RENAME COLUMN state TO status")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_history_missing_ts_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("ALTER TABLE history DROP COLUMN ts")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_store_with_legacy_step_value_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        tid = store.create_step("old style", role="write-code")
        store._conn.execute("UPDATE nodes SET step = 'build' WHERE id = ?", (tid,))
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_store_with_legacy_role_value_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        tid = store.create_step("old style", role="write-code")
        store._conn.execute("UPDATE nodes SET role = 'reviewer' WHERE id = ?", (tid,))
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_store_stamped_below_the_floor_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("PRAGMA user_version = 1")
        store._conn.commit()
        store._conn.close()

        with patch("lightcycle.adapters.sqlite_store._SCHEMA_VERSION", 2):
            with self.assertRaises(SchemaVersionRefused):
                SqliteStore(self._config(root))


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
