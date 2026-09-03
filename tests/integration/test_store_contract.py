import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import lightcycle.cli as cli
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.sqlite_store_factory import (
    make_legacy_sqlite_store, make_sqlite_store, plant_legacy_db,
)
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
        item = s.create_item("an item", "a description")
        tid = s.create_step("build: x", step="build", role="agent", parent=item)
        t = s.get_step(tid)
        self.assertEqual((t.role, t.stage, t.item), ("agent", "build", item))
        self.assertEqual(t.state, "ready")

    def test_claim_and_close_map_status(self):
        s = self._store()
        s.create_step("build: x", step="build", role="agent")
        claimed = s.claim_ready("agent")
        self.assertEqual(claimed.state, "in_progress")
        s.close(claimed.id, "done")
        self.assertEqual(s.get_node(claimed.id).state, "done")
        self.assertEqual(s.get_node(claimed.id).outcome, "done")

    def test_story_artifacts_roundtrip(self):
        s = self._store()
        sid = s.create_item("item: foo", "a description")
        s.add_artifact(sid, "spec", "specs/foo.md", "the spec")
        arts = s.item_artifacts(sid)
        self.assertEqual(
            (arts[0].type, arts[0].value, arts[0].label), ("spec", "specs/foo.md", "the spec")
        )

    def test_ready_reflects_deps_and_closes(self):
        s = self._store()
        blocker = s.create_step("blocker", role="agent")
        blocked = s.create_step("blocked", role="agent")
        s.dep_add(blocked, blocker)
        ready = [t.id for t in s.ready_steps()]
        self.assertIn(blocker, ready)
        self.assertNotIn(blocked, ready)
        s.close(blocker, "done")
        self.assertIn(blocked, [t.id for t in s.ready_steps()])

    def test_status_queue_lane_reflects_open_blocker(self):
        s = self._store()
        blocker = s.create_step("blocker", role="agent")
        blocked = s.create_step("blocked", role="agent")
        s.dep_add(blocked, blocker)
        lanes = StatusUseCase(s).execute().lanes
        self.assertNotIn("blocked", lanes)
        queued = {t.id: t for t in lanes["queue"]}
        self.assertIn(blocked, queued)
        self.assertTrue(queued[blocked].blocked_by)
        self.assertIn(blocker, queued)
        s.close(blocker, "done")
        lanes = StatusUseCase(s).execute().lanes
        queued = {t.id: t for t in lanes["queue"]}
        self.assertIn(blocked, queued)
        self.assertFalse(queued[blocked].blocked_by)

    def test_route_to_human_relabels_and_notes(self):
        s = self._store()
        tid = s.create_step("build: x", step="build", role="agent")
        s.route_to_human(tid, "needs a human")
        t = s.get_node(tid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.state, "ready")
        self.assertIn("needs a human", t.notes or "")

    def test_tasks_closed_since_returns_closed_tasks_on_or_after_date(self):
        s = self._store()
        tid = s.create_step("build: x", step="build", role="agent")
        s.close(tid, "done")
        results = s.nodes_closed_since("2000-01-01")
        self.assertIn(tid, [t.id for t in results])

    def test_tasks_closed_since_excludes_open_tasks(self):
        s = self._store()
        s.create_step("open step", role="agent")
        results = s.nodes_closed_since("2000-01-01")
        self.assertEqual(results, [])

    def test_tasks_closed_since_excludes_stories(self):
        s = self._store()
        sid = s.create_item("closed item", "a description")
        s.close(sid, "merged")
        results = s.nodes_closed_since("2000-01-01")
        self.assertNotIn(sid, [t.id for t in results])

    def test_closed_unretroed_items_returns_closed_items(self):
        s = self._store()
        sid = s.create_item("closed item", "a description")
        s.close(sid, "merged")
        self.assertIn(sid, [t.id for t in s.closed_unretroed_items()])

    def test_closed_unretroed_items_excludes_open_and_retroed_and_origin(self):
        s = self._store()
        s.create_item("open item", "a description")
        retroed = s.create_item("retroed item", "a description")
        s.close(retroed, "merged")
        s.label_add(retroed, "retroed")
        origin = s.create_item("origin item", "a description")
        s.close(origin, "merged")
        s.label_add(origin, "retro-origin")
        ids = [t.id for t in s.closed_unretroed_items()]
        self.assertNotIn(retroed, ids)
        self.assertNotIn(origin, ids)

    def test_last_n_closed_items_returns_closed_items(self):
        s = self._store()
        first = s.create_item("first", "a description")
        s.close(first, "merged")
        second = s.create_item("second", "a description")
        s.close(second, "merged")
        results = s.last_n_closed_items(1)
        self.assertEqual(len(results), 1)

    def test_last_n_closed_items_excludes_open_items(self):
        s = self._store()
        s.create_item("open item", "a description")
        results = s.last_n_closed_items(10)
        self.assertEqual(results, [])

    def test_last_n_closed_items_excludes_nested_steps(self):
        s = self._store()
        item = s.create_item("item", "a description")
        step = s.create_step("build", parent=item)
        s.close(step, "done")
        s.close(item, "merged")
        result_ids = [t.id for t in s.last_n_closed_items(10)]
        self.assertIn(item, result_ids)
        self.assertNotIn(step, result_ids)

    def test_all_tasks_returns_many(self):
        s = self._store()
        created = [s.create_step("step %d" % i, role="agent") for i in range(51)]
        result_ids = {t.id for t in s.all_nodes()}
        for tid in created:
            self.assertIn(tid, result_ids)

    def test_edit_keeps_a_steps_id_and_everything_hanging_off_it(self):
        s = self._store()
        item = s.create_item("item", "a description")
        blocker = s.create_step("blocker", parent=item)
        step = s.create_step("blocked step", parent=item)
        s.dep_add(step, blocker)
        s.label_add(step, "retro-origin")

        new_id = s.edit_node(step, title="renamed")

        self.assertEqual(new_id, step)
        self.assertEqual(s.get_step(step).item, item)
        self.assertEqual(s.get_step(step).blocked_by, [blocker])
        labels = [
            row[0] for row in s._conn.execute(
                "SELECT label FROM labels WHERE node_id = ?", (step,)
            ).fetchall()
        ]
        self.assertIn("retro-origin", labels)

    def test_activate_item_use_case_files_the_entry_step_under_the_item(self):
        s = self._store()
        metas = {"coder": {"model": "sonnet", "step": "build", "routes": {"done": "review"}}}
        workflow = graph_text_from_metas(metas, entry="build")
        flow = FlowService(FakeFs(metas, workflow=workflow), s)

        item = s.create_item("add refunds", "a description")
        resp = ActivateItemUseCase(s, flow, None, None).execute(
            ActivateItemInput(item=item, workflow="standard")
        )

        self.assertEqual(s.get_node(item).state, "ready")
        self.assertEqual(s.get_node(resp.step).parent, item)

    def test_cmd_set_backlog_links_the_resolved_backlog_to_the_item(self):
        s = self._store()
        cli.set_container(Container(store=s))
        item = s.create_item("owning item", "a description")
        backlog_item = s.create_item("a backlog todo", "a description")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_set([item, "--backlog", backlog_item]) or 0
        self.assertEqual(rc, 0, err.getvalue())

        arts = s.item_artifacts(item)
        self.assertTrue(
            any(a.type == "resolves" and a.value == backlog_item for a in arts)
        )


class TestSqliteStoreRoleCollapseMigration(unittest.TestCase):
    def _item(self):
        return {"id": "GRID-1", "type": "item", "title": "an item",
                "state": "backlogged", "description": "d"}

    def _step(self, **kw):
        base = {"id": "GRID-1.1", "type": "step", "title": "build: x", "state": "ready",
                "step": "build", "parent": "GRID-1"}
        base.update(kw)
        return base

    def test_a_stage_named_role_is_rewritten_to_agent_on_open(self):
        s = make_legacy_sqlite_store([self._item(), self._step(role="coder")])
        self.assertEqual(s.get_step("GRID-1.1").role, "agent")

    def test_a_human_role_is_left_alone(self):
        s = make_legacy_sqlite_store(
            [self._item(), self._step(step="await-merge", role="human")])
        self.assertEqual(s.get_step("GRID-1.1").role, "human")

    def test_an_item_carries_no_role_at_all(self):
        s = make_legacy_sqlite_store([self._item()])
        self.assertFalse(hasattr(s.get_item("GRID-1"), "role"))


class TestSqliteStoreBriefMigration(unittest.TestCase):
    def _item(self, description):
        return {"id": "GRID-1", "type": "item", "title": "an item",
                "state": "backlogged", "description": description}

    def _brief(self, text):
        return {"item_id": "GRID-1", "atype": "brief", "value": text, "kind": "filepath"}

    def test_a_brief_fills_an_empty_description(self):
        s = make_legacy_sqlite_store([self._item("")], [self._brief("the settled design")])
        self.assertEqual(s.get_item("GRID-1").description, "the settled design")

    def test_an_existing_description_is_not_overwritten(self):
        s = make_legacy_sqlite_store(
            [self._item("the real description")], [self._brief("a stale brief")])
        self.assertEqual(s.get_item("GRID-1").description, "the real description")

    def test_every_brief_artifact_is_dropped(self):
        s = make_legacy_sqlite_store(
            [self._item("the real description")], [self._brief("a stale brief")])
        kept = [a for a in s.item_artifacts("GRID-1") if a.type == "brief"]
        self.assertEqual(kept, [])


class TestSqliteStoreNodeSplitMigration(unittest.TestCase):
    def test_a_legacy_store_splits_into_items_and_steps(self):
        s = make_legacy_sqlite_store([
            {"id": "GRID-1", "type": "item", "title": "an item", "state": "backlogged",
             "description": "d", "workflow": "o/w@sha"},
            {"id": "GRID-1.1", "type": "step", "title": "build: x", "state": "ready",
             "step": "build", "role": "agent", "parent": "GRID-1", "notes": "a note"},
        ], [{"item_id": "GRID-1", "atype": "repo", "value": "acme/app"}])

        item = s.get_item("GRID-1")
        step = s.get_step("GRID-1.1")

        self.assertEqual((item.description, item.repo, item.workflow),
                         ("d", "acme/app", "o/w@sha"))
        self.assertEqual((step.item, step.stage, step.notes), ("GRID-1", "build", "a note"))
        self.assertFalse(hasattr(step, "description"))

    def test_a_reflection_artifact_becomes_the_steps_reflection(self):
        s = make_legacy_sqlite_store([
            {"id": "GRID-1", "type": "item", "title": "an item", "state": "backlogged",
             "description": "d"},
            {"id": "GRID-1.1", "type": "step", "title": "build: x", "state": "done",
             "step": "build", "role": "agent", "parent": "GRID-1"},
        ], [{"item_id": "GRID-1.1", "atype": "reflection", "value": "what got in the way",
             "internal": True}])

        self.assertEqual(s.get_step("GRID-1.1").reflection, "what got in the way")

    def test_a_watched_step_artifact_becomes_the_steps_field(self):
        s = make_legacy_sqlite_store([
            {"id": "GRID-1", "type": "item", "title": "an item", "state": "backlogged",
             "description": "d"},
            {"id": "GRID-1.1", "type": "step", "title": "handle-feedback: x", "state": "ready",
             "step": "handle-feedback", "role": "agent", "parent": "GRID-1"},
        ], [{"item_id": "GRID-1.1", "atype": "watched-step", "value": "GRID-1.2",
             "internal": True}])

        self.assertEqual(s.get_step("GRID-1.1").watched_step, "GRID-1.2")

    def test_a_retired_theme_row_becomes_an_item_not_a_step(self):
        s = make_legacy_sqlite_store([
            {"id": "GRID-9", "type": "theme", "title": "a retired container",
             "state": "backlogged"},
        ])

        self.assertEqual(s.get_item("GRID-9").title, "a retired container")
        self.assertEqual(s.all_steps(), [])

    def test_the_nodes_table_is_dropped(self):
        s = make_legacy_sqlite_store([
            {"id": "GRID-1", "type": "item", "title": "an item", "state": "backlogged",
             "description": "d"},
        ])
        self.assertFalse(s._has_table("nodes"))


class TestSqliteStorePhaseArtifactFold(unittest.TestCase):
    _ITEM = {"id": "GRID-1", "type": "item", "title": "an item",
             "state": "backlogged", "description": "d"}

    def _store(self, *artifacts):
        return make_legacy_sqlite_store(
            [dict(self._ITEM)],
            [{"item_id": "GRID-1", "atype": a[0], "value": a[1],
              "label": a[2] if len(a) > 2 else None} for a in artifacts],
        )

    def test_a_phases_artifacts_become_one_run(self):
        s = self._store(("branch", "feat/x", "code"), ("pr", "https://gh/1", "code"),
                        ("content-pin", "sha1", "code"))

        run = s.current_run("GRID-1", "code")

        self.assertEqual(
            (run.phase, run.branch, run.pr, run.content_pin),
            ("code", "feat/x", "https://gh/1", "sha1"),
        )

    def test_the_recorded_pass_number_becomes_the_runs_pass(self):
        s = self._store(("branch", "feat/x", "code"), ("phase-run", "3", "code"))

        self.assertEqual(s.current_run("GRID-1", "code").pass_id, "GRID-1.p3")
        self.assertEqual([p.n for p in s.passes_of("GRID-1")], [3])

    def test_two_phases_fold_into_two_runs(self):
        s = self._store(("branch", "spec/x", "spec"), ("branch", "feat/x", "code"))

        runs = s.runs_of("GRID-1")

        self.assertEqual({r.phase: r.branch for r in runs}, {"spec": "spec/x", "code": "feat/x"})

    def test_an_unlabelled_artifact_folds_into_a_phaseless_run(self):
        s = self._store(("branch", "feat/x"))

        run = s.current_run("GRID-1", None)

        self.assertEqual((run.phase, run.branch), (None, "feat/x"))

    def test_every_folded_artifact_is_dropped(self):
        s = self._store(("branch", "feat/x", "code"), ("pr", "u", "code"),
                        ("content-pin", "sha", "code"), ("content-pin-pr", "u", "code"),
                        ("phase-run", "2", "code"))

        kept = {a.type for a in s.item_artifacts("GRID-1")}

        self.assertEqual(kept & set(SqliteStore._FOLDED_ARTIFACTS), set())

    def test_an_item_with_no_phase_artifacts_gains_no_pass(self):
        s = self._store()
        self.assertEqual(s.passes_of("GRID-1"), [])

    def test_the_comment_ledger_folds_onto_the_run(self):
        s = make_legacy_sqlite_store(
            [dict(self._ITEM),
             {"id": "GRID-1.1", "type": "step", "title": "await-merge: x", "state": "ready",
              "step": "await-merge", "role": "human", "parent": "GRID-1"}],
            [{"item_id": "GRID-1", "atype": "branch", "value": "feat/x", "label": "code"},
             {"item_id": "GRID-1.1", "atype": "feedback-watermark", "value": "1500.0",
              "internal": True},
             {"item_id": "GRID-1.1", "atype": "feedback-spawned-through", "value": "1600.0",
              "internal": True}],
        )

        run = s.current_run("GRID-1", "code")

        self.assertEqual(
            (run.comments_handled_through, run.comments_dispatched_through),
            ("1500.0", "1600.0"),
        )


class TestSqliteStoreAddsColumnsToTablesThatAlreadyExist(unittest.TestCase):
    def _store_without_the_ledger_columns(self):
        s = make_sqlite_store()
        s._conn.execute("DROP TABLE phase_runs")
        s._conn.execute(
            "CREATE TABLE phase_runs ("
            "  id TEXT PRIMARY KEY, item TEXT NOT NULL, pass_id TEXT NOT NULL, phase TEXT,"
            "  branch TEXT, pr TEXT, content_pin TEXT,"
            "  state TEXT NOT NULL DEFAULT 'open', opened_at TEXT, closed_at TEXT)"
        )
        s._conn.commit()
        s.disconnect()
        return SqliteStore(s._config)

    def test_a_phase_four_runs_table_gains_the_comment_ledger(self):
        s = self._store_without_the_ledger_columns()
        cols = {r[1] for r in s._conn.execute("PRAGMA table_info(phase_runs)").fetchall()}
        self.assertIn("comments_dispatched_through", cols)
        self.assertIn("comments_handled_through", cols)

    def test_reading_a_run_works_after_the_columns_are_added(self):
        s = self._store_without_the_ledger_columns()
        item = s.create_item("an item", "a description")
        pid = s.open_pass(item)
        s.open_run(item, pid, "code")
        self.assertIsNone(s.runs_of(item)[0].comments_handled_through)


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

        tid = store.create_step("write-code: x", role="agent")
        self.assertEqual(store.get_node(tid).title, "write-code: x")

    def test_unstamped_current_store_is_retro_stamped_with_data_intact(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        tid = store.create_step("write-code: x", role="agent")
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

    def _legacy(self, root, alter=None, rows=()):
        config = self._config(root)
        db_path = plant_legacy_db(config, rows)
        conn = sqlite3.connect(db_path)
        if alter:
            conn.execute(alter)
        conn.execute("PRAGMA user_version = 0")
        conn.commit()
        conn.close()
        return config

    def test_store_with_status_column_present_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, "ALTER TABLE nodes ADD COLUMN status TEXT")

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))
        self.assertIn("0.2.27", str(cm.exception))

        conn = sqlite3.connect(os.path.join(root, "store.db"))
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertIn("status", cols)

    def test_store_missing_workflow_column_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, "ALTER TABLE nodes DROP COLUMN workflow")

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_history_status_without_state_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, "ALTER TABLE history RENAME COLUMN state TO status")

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_history_missing_ts_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, "ALTER TABLE history DROP COLUMN ts")

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_store_with_legacy_step_value_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, rows=[{"id": "GRID-1.1", "type": "step", "title": "old style",
                                  "state": "ready", "step": "build", "role": "agent",
                                  "parent": "GRID-1"}])

        with self.assertRaises(SchemaVersionRefused):
            SqliteStore(self._config(root))

    def test_store_with_legacy_role_value_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, rows=[{"id": "GRID-1.1", "type": "step", "title": "old style",
                                  "state": "ready", "step": "write-code", "role": "reviewer",
                                  "parent": "GRID-1"}])

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

        self.assertFalse(store._has_table("nodes"))
        self.assertEqual(store.get_item("i-merged").outcome, "merged")
        self.assertEqual(store.get_step("s-done").outcome, "done")
        self.assertIsNone(store.get_step("s-open").outcome)

    def test_migration_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        self.assertFalse(store._has_table("nodes"))
        self.assertEqual(store.get_item("i-merged").outcome, "merged")

    def test_fresh_store_has_outcome_on_both_tables(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))

        for table in ("items", "steps"):
            cols = {r[1] for r in store._conn.execute(
                "PRAGMA table_info(%s)" % table).fetchall()}
            self.assertNotIn("close_reason", cols)
            self.assertIn("outcome", cols)


class TestSqliteStoreArtifactFieldsMigration(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        with open(cfg_path, "w") as f:
            f.write("shortcode: GRID\n")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _seed_legacy_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_PRE_OUTCOME_NODES_SCHEMA)
        conn.execute("INSERT INTO nodes (id, type, state) VALUES ('i-1', 'item', 'ready')")
        conn.executemany(
            "INSERT INTO artifacts (item_id, atype, value, label) VALUES (?, ?, ?, ?)",
            [
                ("i-1", "spec", "specs/foo.md", None),
                ("i-1", "repo", "grid", None),
                ("i-1", "reflection", "{}", None),
                ("i-1", "resolves", "b-1", None),
                ("i-1", "resolved-by", "s-1", None),
                ("i-1", "watched-step", "s-2", None),
                ("i-1", "feedback-spawned-through", "s-3", None),
                ("i-1", "feedback-watermark", "s-3", None),
            ],
        )
        conn.commit()
        conn.close()

    def test_backfills_kind_from_the_default_kind_table(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        arts = {a.type: a for a in store.item_artifacts("i-1")}
        self.assertEqual(arts["spec"].kind, "filepath")
        self.assertEqual(arts["resolves"].kind, "text")

    def test_backfills_internal_true_only_for_bookkeeping_types(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        store = SqliteStore(self._config(root))

        arts = {a.type: a for a in store.item_artifacts("i-1")}
        for atype in ("resolves", "resolved-by"):
            self.assertTrue(arts[atype].internal, atype)
        self.assertFalse(arts["spec"].internal)

    def test_migration_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_legacy_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        arts = {a.type: a for a in store.item_artifacts("i-1")}
        self.assertEqual(arts["spec"].kind, "filepath")
        self.assertTrue(arts["resolves"].internal)

    def test_fresh_store_artifact_has_declared_kind_and_internal(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store.add_artifact("i-1", "pr", "https://example.com/pr/1")

        art = store.item_artifacts("i-1")[0]
        self.assertEqual(art.kind, "url")
        self.assertFalse(art.internal)


if __name__ == "__main__":
    unittest.main()
