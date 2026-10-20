import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import lightcycle
import lightcycle.cli as cli
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ToolUsage, UsageResume
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs, graph_text_from_metas
from tests.support.sqlite_store_factory import make_sqlite_store, plant_legacy_db
from tests.support.step_factory import create_owned_step
from tests.support.store_contract import StoreContractBase
from lightcycle.adapters.sqlite_store import (
    _LAST_VERSION_ABLE_TO_MIGRATE_NODES_STORES, _SCHEMA_VERSION, SchemaVersionRefused, SqliteStore,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase
from lightcycle.application.work.status import StatusUseCase
from lightcycle.config import Config
from lightcycle.container import Container
from lightcycle.ports.store import StoreError

_INSTALL = "pipx install --force git+https://github.com/kenmclennan/lightcycle@v%s"
PRE_FLOOR_INSTALL = _INSTALL % "0.2.27"
NODES_INSTALL = _INSTALL % "0.6.263"


class TestSqliteStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self, now=None):
        return make_sqlite_store(now=now)

    def make_store_with_context_artifact_types(self, types):
        return make_sqlite_store(extra_config={"context-artifact-types": " ".join(types)})


class TestHeldCommentsSchema(unittest.TestCase):
    def test_the_two_named_indexes_exist_and_there_is_no_foreign_key(self):
        s = make_sqlite_store()
        names = {
            r[0] for r in s._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'held_comments'"
            ).fetchall()
        }
        self.assertTrue({
            "idx_held_comments_step_id", "idx_held_comments_run_id_state"} <= names)
        self.assertEqual(
            s._conn.execute("PRAGMA foreign_key_list(held_comments)").fetchall(), [])

    def test_the_ledger_columns_match_the_design(self):
        s = make_sqlite_store()
        columns = [r[1] for r in s._conn.execute("PRAGMA table_info(held_comments)").fetchall()]
        self.assertEqual(columns, [
            "run_id", "key", "author", "body", "path", "line", "created_at", "state",
            "item_id", "step_id", "decided_at",
        ])

    def test_approved_holds_are_read_through_the_run_state_index(self):
        s = make_sqlite_store()
        plan = " ".join(r[-1] for r in s._conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM held_comments WHERE run_id = ? AND state = ?",
            ("R-1", "approved"),
        ).fetchall())
        self.assertIn("idx_held_comments_run_id_state", plan)

    def test_an_existing_store_without_the_table_gains_it_on_reopen(self):
        s = make_sqlite_store()
        s._conn.execute("DROP TABLE held_comments")
        s._conn.commit()
        s.release()
        reopened = SqliteStore(s._config)
        self.assertTrue(reopened.file_hold("R-1", "inline:1", "m", "b", None, None, 1.0))


class TestSqliteStoreRoundtrips(unittest.TestCase):
    def _store(self):
        return make_sqlite_store()

    def test_create_task_roundtrips_structured_attrs(self):
        s = self._store()
        item = s.create_item("an item", "a description", shortcode="GRID")
        tid = s.create_step(step="build", role="agent", parent=item)
        t = s.get_step(tid)
        self.assertEqual((t.role, t.stage, t.item), ("agent", "build", item))
        self.assertEqual(t.state, State.QUEUED)

    def test_claim_and_close_map_status(self):
        s = self._store()
        create_owned_step(s, "build: x", step="build", role="agent")
        claimed = s.claim_ready("agent")
        self.assertEqual(claimed.state, State.RUNNING)
        s.complete_node(claimed.id, "done")
        self.assertEqual(s.get_node(claimed.id).state, "done")
        self.assertEqual(s.get_node(claimed.id).outcome, "done")

    def test_story_artifacts_roundtrip(self):
        s = self._store()
        sid = s.create_item("item: foo", "a description", shortcode="GRID")
        s.add_artifact(sid, "spec", "specs/foo.md", "the spec")
        arts = s.item_artifacts(sid)
        self.assertEqual(
            (arts[0].type, arts[0].value, arts[0].label), ("spec", "specs/foo.md", "the spec")
        )

    def test_ready_reflects_deps_and_closes(self):
        s = self._store()
        blocker = create_owned_step(s, "blocker", role="agent")
        blocked = create_owned_step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        ready = [t.id for t in s.ready_steps()]
        self.assertIn(blocker, ready)
        self.assertNotIn(blocked, ready)
        s.complete_node(blocker, "done")
        self.assertIn(blocked, [t.id for t in s.ready_steps()])

    def test_status_queue_lane_reflects_open_blocker(self):
        s = self._store()
        blocker = create_owned_step(s, "blocker", role="agent")
        blocked = create_owned_step(s, "blocked", role="agent")
        s.dep_add(blocked, blocker)
        lanes = StatusUseCase(s).execute().lanes
        self.assertNotIn("blocked", lanes)
        queued = {t.id: t for t in lanes["queue"]}
        self.assertIn(blocked, queued)
        self.assertTrue(queued[blocked].blocked_by)
        self.assertIn(blocker, queued)
        s.complete_node(blocker, "done")
        lanes = StatusUseCase(s).execute().lanes
        queued = {t.id: t for t in lanes["queue"]}
        self.assertIn(blocked, queued)
        self.assertFalse(queued[blocked].blocked_by)

    def test_tasks_closed_since_returns_closed_tasks_on_or_after_date(self):
        s = self._store()
        tid = create_owned_step(s, "build: x", step="build", role="agent")
        s.complete_node(tid, "done")
        results = s.nodes_closed_since("2000-01-01")
        self.assertIn(tid, [t.id for t in results])

    def test_tasks_closed_since_excludes_open_tasks(self):
        s = self._store()
        create_owned_step(s, "open step", role="agent")
        results = s.nodes_closed_since("2000-01-01")
        self.assertEqual(results, [])

    def test_tasks_closed_since_excludes_stories(self):
        s = self._store()
        sid = s.create_item("closed item", "a description", shortcode="GRID")
        s.complete_node(sid, "merged")
        results = s.nodes_closed_since("2000-01-01")
        self.assertNotIn(sid, [t.id for t in results])

    def test_closed_unretroed_items_returns_closed_items(self):
        s = self._store()
        sid = s.create_item("closed item", "a description", shortcode="GRID")
        s.complete_node(sid, "merged")
        self.assertIn(sid, [t.id for t in s.closed_unretroed_items()])

    def test_closed_unretroed_items_excludes_open_and_retroed_and_origin(self):
        s = self._store()
        s.create_item("open item", "a description", shortcode="GRID")
        retroed = s.create_item("retroed item", "a description", shortcode="GRID")
        s.complete_node(retroed, "merged")
        s.label_add(retroed, "retroed")
        origin = s.create_item("origin item", "a description", shortcode="GRID")
        s.complete_node(origin, "merged")
        s.label_add(origin, "retro-origin")
        ids = [t.id for t in s.closed_unretroed_items()]
        self.assertNotIn(retroed, ids)
        self.assertNotIn(origin, ids)

    def test_closed_unretroed_passes_returns_a_closed_pass_of_a_still_open_item(self):
        s = self._store()
        item = s.create_item("looping item", "a description", shortcode="GRID")
        pid = s.open_pass(item)
        s.close_pass(pid)
        self.assertIn(pid, [p.id for p in s.closed_unretroed_passes()])

    def test_closed_unretroed_passes_excludes_closed_item_open_retroed_and_origin(self):
        s = self._store()

        closed_item = s.create_item("closed item", "a description", shortcode="GRID")
        closed_item_pass = s.open_pass(closed_item)
        s.close_pass(closed_item_pass)
        s.complete_node(closed_item, "merged")

        open_item = s.create_item("open item", "a description", shortcode="GRID")
        open_pass = s.open_pass(open_item)

        retroed_item = s.create_item("retroed pass item", "a description", shortcode="GRID")
        retroed_pass = s.open_pass(retroed_item)
        s.close_pass(retroed_pass)
        s.label_add(retroed_pass, "retroed")

        origin_item = s.create_item("origin pass item", "a description", shortcode="GRID")
        origin_pass = s.open_pass(origin_item)
        s.close_pass(origin_pass)
        s.label_add(origin_pass, "retro-origin")

        ids = [p.id for p in s.closed_unretroed_passes()]
        self.assertNotIn(closed_item_pass, ids)
        self.assertNotIn(open_pass, ids)
        self.assertNotIn(retroed_pass, ids)
        self.assertNotIn(origin_pass, ids)

    def test_last_n_closed_items_returns_closed_items(self):
        s = self._store()
        first = s.create_item("first", "a description", shortcode="GRID")
        s.complete_node(first, "merged")
        second = s.create_item("second", "a description", shortcode="GRID")
        s.complete_node(second, "merged")
        results = s.last_n_closed_items(1)
        self.assertEqual(len(results), 1)

    def test_last_n_closed_items_excludes_open_items(self):
        s = self._store()
        s.create_item("open item", "a description", shortcode="GRID")
        results = s.last_n_closed_items(10)
        self.assertEqual(results, [])

    def test_last_n_closed_items_excludes_nested_steps(self):
        s = self._store()
        item = s.create_item("item", "a description", shortcode="GRID")
        step = s.create_step(parent=item)
        s.complete_node(step, "done")
        s.complete_node(item, "merged")
        result_ids = [t.id for t in s.last_n_closed_items(10)]
        self.assertIn(item, result_ids)
        self.assertNotIn(step, result_ids)

    def test_all_tasks_returns_many(self):
        s = self._store()
        created = [create_owned_step(s, "step %d" % i, role="agent") for i in range(51)]
        result_ids = {t.id for t in s.all_nodes()}
        for tid in created:
            self.assertIn(tid, result_ids)

    def test_edit_keeps_a_steps_id_and_everything_hanging_off_it(self):
        s = self._store()
        item = s.create_item("item", "a description", shortcode="GRID")
        blocker = s.create_step(parent=item)
        step = s.create_step(parent=item)
        s.dep_add(step, blocker)
        s.label_add(step, "retro-origin")

        new_id = s.edit_node(step)

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

        item = s.create_item("add refunds", "a description", shortcode="GRID")
        resp = ActivateItemUseCase(s, flow, None, None).execute(
            ActivateItemInput(item=item, workflow="standard")
        )

        self.assertEqual(s.get_node(item).state, State.QUEUED)
        self.assertEqual(s.get_node(resp.step).item, item)

    def test_cmd_set_backlog_links_the_resolved_backlog_to_the_item(self):
        s = self._store()
        cli.set_container(Container(store=s))
        item = s.create_item("owning item", "a description", shortcode="GRID")
        backlog_item = s.create_item("a backlog todo", "a description", shortcode="GRID")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.cmd_set([item, "--backlog", backlog_item]) or 0
        self.assertEqual(rc, 0, err.getvalue())

        arts = s.item_artifacts(item)
        self.assertTrue(
            any(a.type == "resolves" and a.value == backlog_item for a in arts)
        )


class TestSqliteStoreLegacyArtifactTypeMigration(unittest.TestCase):
    def _count(self, store, atype):
        return store._conn.execute(
            "SELECT count(*) FROM artifacts WHERE atype = ?", (atype,)
        ).fetchone()[0]

    def test_reopening_deletes_brief_design_and_backlog_artifacts_only(self):
        s = make_sqlite_store()
        config = s._config
        item = s.create_item("an item", "a description", shortcode="GRID")
        for atype in ("brief", "design", "backlog", "pr"):
            s._conn.execute(
                "INSERT INTO artifacts (item_id, atype, value) VALUES (?, ?, ?)",
                (item, atype, "v"),
            )
        s._conn.commit()
        s.release()

        reopened = SqliteStore(config)

        for atype in ("brief", "design", "backlog"):
            self.assertEqual(self._count(reopened, atype), 0)
        self.assertEqual(self._count(reopened, "pr"), 1)


class TestSqliteStoreAbandonedDispositionMigration(unittest.TestCase):
    def _reopen(self, config):
        return SqliteStore(config)

    def test_a_legacy_aborted_disposition_is_migrated_to_abandoned_on_reopen(self):
        s = make_sqlite_store()
        config = s._config
        item = s.create_item("an item", "a description", shortcode="GRID")
        s.complete_node(item, "wontfix", disposition="aborted")
        s.release()

        reopened = self._reopen(config)

        self.assertEqual(reopened.get_node(item).disposition, "abandoned")

    def test_the_migration_is_idempotent_on_a_second_reopen(self):
        s = make_sqlite_store()
        config = s._config
        item = s.create_item("an item", "a description", shortcode="GRID")
        s.complete_node(item, "wontfix", disposition="aborted")
        s.release()
        first = self._reopen(config)
        first.release()

        second = self._reopen(config)

        self.assertEqual(second.get_node(item).disposition, "abandoned")

    def test_a_completed_item_is_untouched_by_the_migration(self):
        s = make_sqlite_store()
        config = s._config
        item = s.create_item("an item", "a description", shortcode="GRID")
        s.complete_node(item, "done", disposition="completed")
        s.release()

        reopened = self._reopen(config)

        self.assertEqual(reopened.get_node(item).disposition, "completed")


class TestSqliteStoreRenamesTheKnowledgeProject(unittest.TestCase):
    def _seeded(self, *identities):
        s = make_sqlite_store()
        config = s._config
        db_path = s._db_path
        s.release()
        conn = sqlite3.connect(db_path)
        for identity in identities:
            conn.execute(
                "INSERT INTO projects (identity, shortcode, local_path, remote, facets) "
                "VALUES (?, ?, ?, ?, ?)",
                (identity, "SC-" + identity, "/path/" + identity, "git@x:" + identity, "a,b"),
            )
        conn.commit()
        conn.close()
        return config

    def _row(self, store, identity):
        project = store.get_project(identity)
        if project is None:
            return None
        return (project.shortcode, project.local_path, project.remote, project.facets)

    def test_knowledge_only_is_renamed_to_guidance_keeping_every_field(self):
        config = self._seeded("knowledge", "acme/x")

        reopened = SqliteStore(config)

        self.assertEqual(
            self._row(reopened, "guidance"),
            ("SC-knowledge", "/path/knowledge", "git@x:knowledge", ("a", "b")),
        )
        self.assertIsNone(reopened.get_project("knowledge"))
        self.assertEqual(
            self._row(reopened, "acme/x"), ("SC-acme/x", "/path/acme/x", "git@x:acme/x", ("a", "b"))
        )

    def test_both_registered_are_left_exactly_as_seeded(self):
        config = self._seeded("knowledge", "guidance", "acme/x")

        reopened = SqliteStore(config)

        self.assertEqual(
            self._row(reopened, "knowledge"),
            ("SC-knowledge", "/path/knowledge", "git@x:knowledge", ("a", "b")),
        )
        self.assertEqual(
            self._row(reopened, "guidance"),
            ("SC-guidance", "/path/guidance", "git@x:guidance", ("a", "b")),
        )
        self.assertIsNotNone(reopened.get_project("acme/x"))

    def test_a_second_reopen_is_a_no_op(self):
        config = self._seeded("knowledge")
        SqliteStore(config).release()

        again = SqliteStore(config)

        self.assertEqual(
            self._row(again, "guidance"),
            ("SC-knowledge", "/path/knowledge", "git@x:knowledge", ("a", "b")),
        )
        self.assertIsNone(again.get_project("knowledge"))


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
        s.release()
        return SqliteStore(s._config)

    def test_a_phase_four_runs_table_gains_the_comment_ledger(self):
        s = self._store_without_the_ledger_columns()
        cols = {r[1] for r in s._conn.execute("PRAGMA table_info(phase_runs)").fetchall()}
        self.assertIn("comments_dispatched_through", cols)
        self.assertIn("comments_handled_through", cols)

    def test_reading_a_run_works_after_the_columns_are_added(self):
        s = self._store_without_the_ledger_columns()
        item = s.create_item("an item", "a description", shortcode="GRID")
        pid = s.open_pass(item)
        s.open_run(item, pid, "code")
        self.assertIsNone(s.runs_of(item)[0].comments_handled_through)


class TestSqliteStoreAddsTheHistoryIndex(unittest.TestCase):
    def _step(self, s, title="t", **kw):
        return create_owned_step(s, title, **kw)

    def _find_history_index(self, conn):
        for row in conn.execute("PRAGMA index_list(history)").fetchall():
            name = row[1]
            cols = [r[2] for r in conn.execute("PRAGMA index_info(%s)" % name).fetchall()]
            if cols == ["node_id", "seq"]:
                return name
        return None

    def _store_without_the_history_index(self):
        s = make_sqlite_store()
        s._conn.execute("DROP TABLE history")
        s._conn.execute(
            "CREATE TABLE history (node_id TEXT NOT NULL, seq INTEGER NOT NULL, "
            "state TEXT NOT NULL, ts TEXT)"
        )
        s._conn.commit()
        s.release()
        return SqliteStore(s._config)

    def test_an_existing_store_missing_the_index_gains_it_on_reopen(self):
        s = self._store_without_the_history_index()
        self.assertIsNotNone(self._find_history_index(s._conn))

    def test_reopening_the_migrated_store_a_second_time_is_idempotent(self):
        s = self._store_without_the_history_index()
        s.release()
        s = SqliteStore(s._config)
        name = self._find_history_index(s._conn)
        self.assertIsNotNone(name)
        count = s._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_history_returns_the_same_rows_in_the_same_order(self):
        s = make_sqlite_store()
        self.assertIsNotNone(self._find_history_index(s._conn))
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.complete_node(tid, "done")
        states = [state for state, _ in s.history(tid)]
        self.assertEqual(states, ["running", "done"])

    def test_the_read_query_uses_the_index_not_a_scan(self):
        s = make_sqlite_store()
        tid = self._step(s, "t", role="agent")
        s.claim_ready("agent")
        s.complete_node(tid, "done")

        plan = s._conn.execute(
            "EXPLAIN QUERY PLAN SELECT state, ts FROM history WHERE node_id = ? ORDER BY seq ASC",
            (tid,),
        ).fetchall()
        plan_text = " ".join(row[-1] for row in plan)
        self.assertIn("USING INDEX", plan_text)
        self.assertNotIn("SCAN history", plan_text)


class TestSqliteStoreAddsDispositionToItems(unittest.TestCase):
    def _store_without_disposition(self):
        s = make_sqlite_store()
        item = s.create_item("an item", "a description", shortcode="GRID")
        s.complete_node(item, "done")
        s._conn.execute("ALTER TABLE items RENAME TO items_old")
        s._conn.execute(
            "CREATE TABLE items ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', description TEXT,"
            "  state TEXT NOT NULL DEFAULT 'backlogged', repo TEXT, workflow TEXT,"
            "  outcome TEXT, project TEXT, created_at TEXT, closed_at TEXT)"
        )
        s._conn.execute(
            "INSERT INTO items (id, title, description, state, repo, workflow, outcome, "
            "project, created_at, closed_at) "
            "SELECT id, title, description, state, repo, workflow, outcome, project, "
            "created_at, closed_at FROM items_old"
        )
        s._conn.execute("DROP TABLE items_old")
        s._conn.commit()
        s.release()
        return item, SqliteStore(s._config)

    def test_a_pre_disposition_items_table_gains_the_column(self):
        _, s = self._store_without_disposition()
        cols = {r[1] for r in s._conn.execute("PRAGMA table_info(items)").fetchall()}
        self.assertIn("disposition", cols)

    def test_the_column_is_null_for_an_existing_closed_item_until_it_is_reclosed(self):
        item, s = self._store_without_disposition()
        self.assertIsNone(s.get_node(item).disposition)

    def test_reopening_the_migrated_store_is_idempotent(self):
        item, s = self._store_without_disposition()
        s.release()
        s = SqliteStore(s._config)
        self.assertIsNone(s.get_node(item).disposition)


class TestSqliteStoreAddsNoteToItems(unittest.TestCase):
    def _store_without_note(self):
        s = make_sqlite_store()
        item = s.create_item("an item", "a description", shortcode="GRID")
        s.complete_node(item, "done")
        s._conn.execute("ALTER TABLE items RENAME TO items_old")
        s._conn.execute(
            "CREATE TABLE items ("
            "  id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '', description TEXT,"
            "  state TEXT NOT NULL DEFAULT 'backlogged', repo TEXT, workflow TEXT,"
            "  outcome TEXT, disposition TEXT, project TEXT, created_at TEXT, closed_at TEXT)"
        )
        s._conn.execute(
            "INSERT INTO items (id, title, description, state, repo, workflow, outcome, "
            "disposition, project, created_at, closed_at) "
            "SELECT id, title, description, state, repo, workflow, outcome, disposition, "
            "project, created_at, closed_at FROM items_old"
        )
        s._conn.execute("DROP TABLE items_old")
        s._conn.commit()
        s.release()
        return item, SqliteStore(s._config)

    def test_a_pre_note_items_table_gains_the_column(self):
        _, s = self._store_without_note()
        cols = {r[1] for r in s._conn.execute("PRAGMA table_info(items)").fetchall()}
        self.assertIn("note", cols)

    def test_the_column_is_null_for_an_existing_closed_item(self):
        item, s = self._store_without_note()
        self.assertIsNone(s.get_node(item).note)


class TestSqliteStoreAddsClaimEpochToSteps(unittest.TestCase):
    def _store_without_claim_epoch(self):
        s = make_sqlite_store()
        tid = create_owned_step(s, "write-code: x", role="agent")
        s.claim_ready("agent")
        cols = [
            r for r in s._conn.execute("PRAGMA table_info(steps)").fetchall()
            if r[1] != "claim_epoch"
        ]
        names = ", ".join(c[1] for c in cols)
        col_defs = ", ".join(
            "%s %s%s%s"
            % (
                c[1],
                c[2],
                " NOT NULL" if c[3] else "",
                (" DEFAULT %s" % c[4]) if c[4] is not None else "",
            )
            for c in cols
        )
        pk_cols = [c[1] for c in cols if c[5]]
        if pk_cols:
            col_defs += ", PRIMARY KEY (%s)" % ", ".join(pk_cols)
        s._conn.execute("ALTER TABLE steps RENAME TO steps_old")
        s._conn.execute("CREATE TABLE steps (%s)" % col_defs)
        s._conn.execute(
            "INSERT INTO steps (%s) SELECT %s FROM steps_old" % (names, names)
        )
        s._conn.execute("DROP TABLE steps_old")
        s._conn.commit()
        s.release()
        return tid, SqliteStore(s._config)

    def test_a_pre_claim_epoch_steps_table_gains_the_column(self):
        _, s = self._store_without_claim_epoch()
        cols = {r[1] for r in s._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertIn("claim_epoch", cols)

    def test_the_column_defaults_to_zero_for_an_existing_row(self):
        tid, s = self._store_without_claim_epoch()
        row = s._conn.execute(
            "SELECT claim_epoch FROM steps WHERE id = ?", (tid,)
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_reopening_the_migrated_store_a_second_time_is_idempotent(self):
        tid, s = self._store_without_claim_epoch()
        s.release()
        s = SqliteStore(s._config)
        row = s._conn.execute(
            "SELECT claim_epoch FROM steps WHERE id = ?", (tid,)
        ).fetchone()
        self.assertEqual(row[0], 0)


class TestSqliteStoreTranslatesSqliteErrors(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def test_corrupt_store_surfaces_store_error_not_sqlite_operational_error(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("DROP TABLE items")

        with self.assertRaises(StoreError):
            store.all_items()


class TestSqliteStoreSchemaVersionFloor(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def test_fresh_store_is_stamped_current_and_usable(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))

        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, _SCHEMA_VERSION)

        tid = create_owned_step(store, "write-code: x", role="agent")
        self.assertEqual(store.get_item(store.get_node(tid).item).title, "write-code: x")

    def test_unstamped_current_store_is_retro_stamped_with_data_intact(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        tid = create_owned_step(store, "write-code: x", role="agent")
        store._conn.execute("PRAGMA user_version = 0")
        store._conn.commit()
        store._conn.close()

        reopened = SqliteStore(self._config(root))

        version = reopened._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, _SCHEMA_VERSION)
        self.assertEqual(reopened.get_item(reopened.get_node(tid).item).title, "write-code: x")

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

    def test_legacy_projects_table_without_facets_migrates_and_reads_no_facets(self):
        root = tempfile.mkdtemp()
        config = self._config(root)
        first = SqliteStore(config)
        db_path = first._db_path
        first.release()
        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE projects")
        conn.execute(
            "CREATE TABLE projects (identity TEXT PRIMARY KEY, shortcode TEXT, "
            "local_path TEXT, remote TEXT)"
        )
        conn.execute("INSERT INTO projects VALUES ('acme/old', 'OLD', '/p/old', NULL)")
        conn.commit()
        conn.close()

        store = SqliteStore(config)

        self.assertEqual(store.get_project("acme/old").facets, ())
        self.assertEqual(store.list_projects()[0].facets, ())

    def test_store_with_status_column_present_is_refused(self):
        root = tempfile.mkdtemp()
        self._legacy(root, "ALTER TABLE nodes ADD COLUMN status TEXT")

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))
        self.assertIn(PRE_FLOOR_INSTALL, str(cm.exception))

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

    def _plant_nodes_store(self, root, user_version, alter=None):
        config = self._config(root)
        db_path = plant_legacy_db(config, [{"id": "GRID-1.1", "type": "step", "title": "old style",
                                            "state": "ready", "step": "build", "role": "agent",
                                            "parent": "GRID-1"}])
        conn = sqlite3.connect(db_path)
        if alter:
            conn.execute(alter)
        conn.execute("PRAGMA user_version = %d" % user_version)
        conn.commit()
        conn.close()
        return db_path

    def _assert_nodes_store_untouched(self, db_path, user_version):
        conn = sqlite3.connect(db_path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], user_version)
        rows = conn.execute("SELECT id, type, step, role, parent FROM nodes").fetchall()
        self.assertEqual(rows, [("GRID-1.1", "step", "build", "agent", "GRID-1")])
        cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        self.assertIn("workflow", cols)
        self.assertNotIn("status", cols)
        conn.close()

    def test_unstamped_store_with_current_shaped_nodes_table_is_refused_naming_the_nodes_release(self):
        root = tempfile.mkdtemp()
        db_path = self._plant_nodes_store(root, 0)

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))

        message = str(cm.exception)
        self.assertIn(NODES_INSTALL, message)
        self.assertIn("pre-split nodes table", message)
        self.assertNotIn("0.2.27", message)
        self._assert_nodes_store_untouched(db_path, 0)

    def test_stamped_store_with_nodes_table_is_refused_naming_the_nodes_release(self):
        root = tempfile.mkdtemp()
        db_path = self._plant_nodes_store(root, _SCHEMA_VERSION)

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))

        message = str(cm.exception)
        self.assertIn(NODES_INSTALL, message)
        self.assertIn("pre-split nodes table", message)
        self._assert_nodes_store_untouched(db_path, _SCHEMA_VERSION)

    def test_legacy_shaped_nodes_table_keeps_the_pre_floor_message(self):
        root = tempfile.mkdtemp()
        self._plant_nodes_store(root, 0, "ALTER TABLE nodes ADD COLUMN status TEXT")

        with self.assertRaises(SchemaVersionRefused) as cm:
            SqliteStore(self._config(root))

        self.assertIn(PRE_FLOOR_INSTALL, str(cm.exception))
        self.assertNotIn("pre-split nodes table", str(cm.exception))

    def test_nodes_release_is_a_semver_after_the_floor_and_not_ahead_of_the_engine(self):
        def parse(v):
            major, minor, patch = v.split(".")
            return (int(major), int(minor), int(patch))

        named = parse(_LAST_VERSION_ABLE_TO_MIGRATE_NODES_STORES)

        self.assertGreater(named, parse("0.2.27"))
        self.assertLessEqual(named, parse(lightcycle.__version__))

    def test_store_stamped_below_the_floor_is_refused(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        store._conn.execute("PRAGMA user_version = %d" % _SCHEMA_VERSION)
        store._conn.commit()
        store._conn.close()

        with patch("lightcycle.adapters.sqlite_store._SCHEMA_VERSION", _SCHEMA_VERSION + 1):
            with self.assertRaises(SchemaVersionRefused) as cm:
                SqliteStore(self._config(root))

        self.assertIn(PRE_FLOOR_INSTALL, str(cm.exception))


class TestSqliteStoreSchema2Migration(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _version_1_store(self, root):
        store = SqliteStore(self._config(root))
        db_path = store._db_path
        store.release()
        conn = sqlite3.connect(db_path)
        for column in ("previous_step", "report", "log_path"):
            conn.execute("ALTER TABLE steps DROP COLUMN %s" % column)
        conn.execute("DROP TABLE step_inputs")
        conn.execute("INSERT INTO items (id, title, state) VALUES ('APP-1', 't', 'ready')")
        for sid, stage, outcome, state, created, closed, notes in (
            ("APP-1.1", "build", "done", "done", "2026-01-01T09:00:00+00:00",
             "2026-01-01T10:00:00+00:00", "outcome: done"),
            ("APP-1.2", "gate", "approved", "done", "2026-01-01T11:00:00+00:00",
             "2026-01-01T11:30:00+00:00",
             "from build (done): fix the tests\nand the lint\noutcome: approved"),
            ("APP-1.3", "review", "rejected", "done", "2026-01-01T09:00:00+00:00",
             "2026-01-01T10:00:00+00:00", None),
            ("APP-1.4", "review", "rejected", "done", "2026-01-01T09:30:00+00:00",
             "2026-01-01T12:00:00+00:00", None),
            ("APP-1.5", "review", "rejected", "done", "2026-01-01T09:45:00+00:00",
             "2026-01-01T14:00:00+00:00", None),
            ("APP-1.6", "rework", "done", "ready", "2026-01-01T13:00:00+00:00", None,
             "from review (rejected): add tests"),
            ("APP-1.7", "orphan", None, "ready", "2026-01-01T13:30:00+00:00", None,
             "from ghost (done): nothing wrote this"),
        ):
            conn.execute(
                "INSERT INTO steps (id, item, stage, outcome, state, created_at, closed_at, notes) "
                "VALUES (?, 'APP-1', ?, ?, ?, ?, ?, ?)",
                (sid, stage, outcome, state, created, closed, notes))
        conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, internal) VALUES ('APP-1.1', 'log', '/l/old.log', 1)")
        conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, internal) VALUES ('APP-1.1', 'log', '/l/new.log', 1)")
        conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, internal) VALUES ('APP-1', 'log', '/l/item.log', 0)")
        conn.execute("INSERT INTO items (id, title, state) VALUES ('APP-2', 't', 'ready')")
        conn.execute(
            "INSERT INTO steps (id, item, stage, state, created_at) "
            "VALUES ('APP-2.1', 'APP-2', 'poll', 'ready', '2026-01-02T09:00:00+00:00')")
        conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, internal) VALUES ('APP-2', 'log', '/l/guard.log', 0)")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()
        return db_path

    def _open(self, root):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            store = SqliteStore(self._config(root))
        return store, err.getvalue()

    def test_a_version_1_store_opens_migrates_and_is_stamped_2(self):
        root = tempfile.mkdtemp()
        self._version_1_store(root)

        store, _err = self._open(root)

        self.assertEqual(store._conn.execute("PRAGMA user_version").fetchone()[0], 2)
        columns = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertLessEqual({"previous_step", "report", "log_path"}, columns)
        self.assertEqual(store.step_inputs("APP-1.1"), None)

    def test_the_backfill_matches_by_stage_and_outcome_and_counts_the_unmatched(self):
        root = tempfile.mkdtemp()
        self._version_1_store(root)

        store, err = self._open(root)

        self.assertEqual(store.last_migration, {"matched": 2, "unmatched": 1, "logs": 2})
        self.assertIn(
            "schema 2: backfilled 2 reports (1 unmatched), copied 2 logs", err)
        self.assertEqual(store.get_node("APP-1.1").report, "fix the tests\nand the lint")
        self.assertEqual(store.get_node("APP-1.2").previous_step, "APP-1.1")
        self.assertEqual(store.get_node("APP-1.4").report, "add tests")
        self.assertIsNone(store.get_node("APP-1.3").report)
        self.assertIsNone(store.get_node("APP-1.5").report)
        self.assertEqual(store.get_node("APP-1.6").previous_step, "APP-1.4")
        self.assertIsNone(store.get_node("APP-1.7").previous_step)

    def test_the_backfill_leaves_the_original_notes_untouched(self):
        root = tempfile.mkdtemp()
        self._version_1_store(root)

        store, _err = self._open(root)

        self.assertEqual(
            store.get_node("APP-1.2").notes,
            "from build (done): fix the tests\nand the lint\noutcome: approved")
        self.assertEqual(
            store.get_node("APP-1.7").notes, "from ghost (done): nothing wrote this")

    def test_log_rows_are_copied_onto_the_step_and_left_in_place(self):
        root = tempfile.mkdtemp()
        self._version_1_store(root)

        store, _err = self._open(root)

        self.assertEqual(store.get_node("APP-1.1").log_path, "/l/new.log")
        self.assertEqual(
            len([a for a in store.item_artifacts("APP-1.1") if a.type == "log"]), 2)
        self.assertEqual(
            len([a for a in store.item_artifacts("APP-1") if a.type == "log"]), 1)
        self.assertEqual(store.get_node("APP-2.1").log_path, "/l/guard.log")
        self.assertIsNone(store.get_node("APP-1.2").log_path)

    def test_reopening_a_version_2_store_runs_no_backfill(self):
        root = tempfile.mkdtemp()
        self._version_1_store(root)
        first, _err = self._open(root)
        first.release()

        second, err = self._open(root)

        self.assertIsNone(second.last_migration)
        self.assertEqual(err, "")

    def test_a_fresh_store_is_stamped_2_with_no_backfill(self):
        root = tempfile.mkdtemp()

        store, err = self._open(root)

        self.assertEqual(store._conn.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertIsNone(store.last_migration)
        self.assertEqual(err, "")

    def test_step_inputs_round_trip_and_replace(self):
        root = tempfile.mkdtemp()
        store, _err = self._open(root)
        step = create_owned_step(store, "x", role="agent")

        store.save_step_inputs(step, "t1", '{"a": 1}')
        store.save_step_inputs(step, "t2", '{"a": 2}')

        self.assertEqual(store.step_inputs(step), ("t2", '{"a": 2}'))

    def test_report_log_and_previous_survive_the_real_store(self):
        root = tempfile.mkdtemp()
        store, _err = self._open(root)
        first = create_owned_step(store, "x", role="agent")
        item = store.get_node(first).item
        second = store.create_step(step="review", role="agent", parent=item, previous=first)

        store.set_report(first, "the report")
        store.set_log(second, "/l/s.log")

        self.assertEqual(store.get_node(first).report, "the report")
        self.assertEqual(store.get_node(second).previous_step, first)
        self.assertEqual(store.get_node(second).log_path, "/l/s.log")
        self.assertEqual([r.node_id for r in store.artifact_log(item)], [])


_PRE_USAGE_STEPS_SCHEMA = """
CREATE TABLE steps (
    id TEXT PRIMARY KEY,
    item TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    stage TEXT,
    pass_id TEXT,
    role TEXT,
    state TEXT NOT NULL DEFAULT 'ready',
    assignee TEXT,
    model TEXT,
    outcome TEXT,
    notes TEXT,
    reflection TEXT,
    watched_step TEXT,
    park_reason TEXT,
    park_needs TEXT,
    park_tried TEXT,
    created_at TEXT,
    fired_at TEXT,
    closed_at TEXT,
    active_seconds REAL
);

CREATE TABLE items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT,
    state TEXT NOT NULL DEFAULT 'backlogged',
    repo TEXT,
    workflow TEXT,
    outcome TEXT,
    project TEXT,
    created_at TEXT,
    closed_at TEXT
);
"""


class TestSqliteStoreUsageColumnsMigration(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _seed_pre_usage_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_PRE_USAGE_STEPS_SCHEMA)
        conn.execute(
            "INSERT INTO steps (id, item, state, created_at) "
            "VALUES ('s-1', 'i-1', 'ready', '2026-01-01')"
        )
        conn.commit()
        conn.close()

    def test_existing_store_gains_usage_columns_defaulted_and_the_outcome_index(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        for col in (
            "usage_input_tokens", "usage_output_tokens", "usage_cache_read_tokens",
            "usage_cache_creation_tokens", "usage_cost_usd", "usage_cost_basis",
            "usage_rates_used", "usage_thinking_tokens", "turn_count",
        ):
            self.assertIn(col, cols)

        t = store.get_step("s-1")
        self.assertEqual(t.usage_input_tokens, 0)
        self.assertEqual(t.usage_output_tokens, 0)
        self.assertEqual(t.usage_cache_read_tokens, 0)
        self.assertEqual(t.usage_cache_creation_tokens, 0)
        self.assertEqual(t.usage_cost_usd, Cost())
        self.assertIsNone(t.usage_cost_basis)
        self.assertIsNone(t.usage_rates_used)
        self.assertIsNone(t.usage_thinking_tokens)
        self.assertEqual(t.turn_count, 0)

        idx = store._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_steps_outcome'"
        ).fetchone()
        self.assertIsNotNone(idx)

    def test_existing_store_gains_step_tool_usage_and_backfill_log_tables(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        for table in ("step_tool_usage", "usage_backfill_log"):
            self.assertTrue(store._has_table(table))

        idx = store._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_step_tool_usage_tool'"
        ).fetchone()
        self.assertIsNotNone(idx)

    def test_migration_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        t = store.get_step("s-1")
        self.assertEqual(t.usage_input_tokens, 0)

    def test_existing_backfill_log_row_gains_had_result_line_as_null(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        SqliteStore(self._config(root))
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.execute(
            "INSERT INTO usage_backfill_log (log_file, step, ingested_at) "
            "VALUES ('/l/legacy.log', 's-1', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(usage_backfill_log)").fetchall()}
        self.assertIn("had_result_line", cols)
        self.assertEqual(store.unclassified_backfill_logs(), [("/l/legacy.log", "s-1")])


class TestSqliteStoreDropsStepReflectionColumn(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _seed_pre_usage_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_PRE_USAGE_STEPS_SCHEMA)
        conn.execute(
            "INSERT INTO steps (id, item, state, created_at, reflection) "
            "VALUES ('s-1', 'i-1', 'ready', '2026-01-01', 'a stale value')"
        )
        conn.commit()
        conn.close()

    def test_existing_store_drops_the_reflection_column(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertNotIn("reflection", cols)

    def test_drop_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertNotIn("reflection", cols)

    def test_other_step_fields_survive_the_drop(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        t = store.get_step("s-1")
        self.assertFalse(hasattr(t, "reflection"))
        self.assertEqual(t.created_at, "2026-01-01")


class TestSqliteStoreDropsGoalStateOfPlayColumns(unittest.TestCase):
    COLUMNS = {"id", "title", "description", "project", "status", "created_at", "updated_at"}

    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _plant_legacy_goal(self, root):
        config = self._config(root)
        SqliteStore(config)._conn.close()
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(
            "DROP TABLE goals;"
            "CREATE TABLE goals (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "description TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'not started', created_at TEXT, updated_at TEXT, "
            "state_of_play TEXT NOT NULL DEFAULT '', state_of_play_at TEXT, "
            "state_of_play_step TEXT);"
        )
        conn.execute(
            "INSERT INTO goals (id, title, description, project, status, state_of_play, "
            "state_of_play_at, state_of_play_step) VALUES "
            "('G-1', 'g', 'kept description', 'lightcycle', 'in progress', 'old plan', "
            "'2026-09-01T10:00:00+01:00', 'LC-1.1')"
        )
        conn.commit()
        conn.close()
        return config

    def _columns(self, store):
        return {r[1] for r in store._conn.execute("PRAGMA table_info(goals)").fetchall()}

    def test_existing_store_drops_the_three_columns_and_keeps_the_row(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._plant_legacy_goal(root))

        self.assertEqual(self._columns(store), self.COLUMNS)
        goal = store.get_goal("G-1")
        self.assertEqual(
            (goal.title, goal.description, goal.project, goal.status),
            ("g", "kept description", "lightcycle", "in progress"),
        )

    def test_drop_is_idempotent_and_never_re_added_on_reopen(self):
        root = tempfile.mkdtemp()
        config = self._plant_legacy_goal(root)
        SqliteStore(config)._conn.close()
        store = SqliteStore(config)

        self.assertEqual(self._columns(store), self.COLUMNS)
        self.assertEqual(store.get_goal("G-1").description, "kept description")

    def test_a_fresh_store_has_exactly_the_seven_columns(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))

        self.assertEqual(self._columns(store), self.COLUMNS)


class TestSqliteStoreDropsStepTitleColumn(unittest.TestCase):
    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _seed_pre_usage_store(self, root):
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(_PRE_USAGE_STEPS_SCHEMA)
        conn.execute(
            "INSERT INTO steps (id, item, state, created_at, title) "
            "VALUES ('s-1', 'i-1', 'ready', '2026-01-01', 'build: a stale composite title')"
        )
        conn.commit()
        conn.close()

    def test_fresh_store_has_no_title_column(self):
        root = tempfile.mkdtemp()
        store = SqliteStore(self._config(root))
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertNotIn("title", cols)

    def test_existing_store_drops_the_title_column(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertNotIn("title", cols)

    def test_drop_is_idempotent_on_reopen(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        SqliteStore(self._config(root))
        store = SqliteStore(self._config(root))

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(steps)").fetchall()}
        self.assertNotIn("title", cols)

    def test_other_step_fields_survive_the_drop(self):
        root = tempfile.mkdtemp()
        self._seed_pre_usage_store(root)
        store = SqliteStore(self._config(root))

        t = store.get_step("s-1")
        self.assertFalse(hasattr(t, "title"))
        self.assertEqual(t.created_at, "2026-01-01")


class TestSqliteStoreAtomicity(unittest.TestCase):
    def _store(self):
        return make_sqlite_store()

    def test_reclaim_rolls_back_state_when_history_write_fails(self):
        s = self._store()
        tid = create_owned_step(s, "t", role="agent")
        s.claim_ready("agent")
        with patch.object(s, "_record_history", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                s.reclaim(tid)
        self.assertEqual(s.get_node(tid).state, State.RUNNING)

    def test_record_live_usage_rolls_back_checkpoint_when_attribution_write_fails(self):
        s = self._store()
        tid = create_owned_step(s, "t", role="agent")
        with patch.object(
            s, "_record_attribution_nocommit", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                s.record_live_usage(
                    spawnid="sp1",
                    resume=UsageResume(
                        log_file="/l/x.log", offset=100, message_ids=[],
                        pending_tool_use={}, posted_turn_count=1, posted_tool_usage={},
                        posted_input_tokens=5, posted_output_tokens=0,
                        posted_cache_read_tokens=0, posted_cache_creation_tokens=0,
                        posted_cost_usd=0.0,
                    ),
                    tid=tid, input_tokens=5, output_tokens=0, cache_read_tokens=0,
                    cache_creation_tokens=0, cost_usd=0.0, cost_basis=None,
                    thinking_tokens=None, turn_count=1,
                    tool_usage={"Read": ToolUsage(calls=1, bytes=10)},
                )
        self.assertIsNone(s.usage_accrual_state("sp1"))
        self.assertEqual(s.get_node(tid).usage_input_tokens, 0)


if __name__ == "__main__":
    unittest.main()


class TestSqliteStoreGoalsMigration(unittest.TestCase):
    G1_OUTCOME = "Problem: agents starve.\n\nOutcome: fewer stalls.\n\n- Constraint one"
    G1_QUESTION = "Is max-agents: 5 on 16 GB itself the miscalibration?"

    def _config(self, root):
        cfg_path = os.path.join(root, "config")
        return Config(environ={"LC_HOME": root, "LC_CONFIG": cfg_path})

    def _plant(self, root, goals, questions=()):
        config = self._config(root)
        SqliteStore(config)._conn.close()
        conn = sqlite3.connect(os.path.join(root, "store.db"))
        conn.executescript(
            "DROP TABLE goals;"
            "CREATE TABLE goals (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
            "outcome TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'not started', created_at TEXT, updated_at TEXT);"
            "CREATE TABLE goal_questions (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "goal_id TEXT NOT NULL, body TEXT NOT NULL, raised_at TEXT, resolved_at TEXT, "
            "resolution TEXT);"
            "CREATE INDEX idx_goal_questions_goal_id ON goal_questions(goal_id);"
            "DROP TABLE goal_log;"
            "CREATE TABLE goal_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "goal_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT);"
            "CREATE INDEX idx_goal_log_goal_id ON goal_log(goal_id);"
        )
        for gid, title, outcome, scope in goals:
            conn.execute(
                "INSERT INTO goals (id, title, outcome, scope, status) VALUES (?, ?, ?, ?, 'in progress')",
                (gid, title, outcome, scope),
            )
        for gid, body, resolved in questions:
            conn.execute(
                "INSERT INTO goal_questions (goal_id, body, resolved_at, resolution) VALUES (?, ?, ?, ?)",
                (gid, body, "2026-09-18" if resolved else None, "r" if resolved else None),
            )
        conn.execute("INSERT INTO goal_log (goal_id, body, created_at) VALUES ('G-1', 'kept log', '2026-09-19T09:30:00+01:00')")
        conn.execute("INSERT INTO goal_items (goal_id, item_id) VALUES ('G-1', 'LC-1')")
        conn.commit()
        conn.close()
        return config

    def _tables(self, store):
        return {
            r[0] for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    def test_g1_shape_keeps_outcome_verbatim_and_carries_only_the_open_question(self):
        root = tempfile.mkdtemp()
        config = self._plant(
            root, [("G-1", "g", self.G1_OUTCOME, "")],
            [("G-1", self.G1_QUESTION, False), ("G-1", "settled?", True)],
        )

        store = SqliteStore(config)

        goal = store.get_goal("G-1")
        self.assertEqual(
            goal.description, "%s\n\n## Open questions\n\n- %s" % (self.G1_OUTCOME, self.G1_QUESTION)
        )
        self.assertNotIn("settled?", goal.description)
        self.assertEqual((goal.project, goal.status), ("", "in progress"))
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(goals)").fetchall()}
        self.assertEqual(
            cols,
            {
                "id", "title", "description", "project", "status", "created_at", "updated_at",
            },
        )
        self.assertNotIn("goal_questions", self._tables(store))
        self.assertEqual([e.body for e in store.goal_log("G-1")], ["kept log"])
        self.assertEqual(store.goal_items("G-1"), ["LC-1"])

    def test_goal_log_gains_a_title_column_keeping_legacy_rows_and_indexes(self):
        root = tempfile.mkdtemp()
        config = self._plant(root, [("G-1", "g", self.G1_OUTCOME, "")])

        store = SqliteStore(config)

        cols = [r[1] for r in store._conn.execute("PRAGMA table_info(goal_log)").fetchall()]
        self.assertIn("title", cols)
        legacy = store.goal_log("G-1")[0]
        self.assertEqual(
            (legacy.title, legacy.body, legacy.created_at, legacy.id),
            ("", "kept log", "2026-09-19T09:30:00+01:00", 1),
        )
        store.add_goal_log("G-1", "new title", "new body")
        self.assertEqual([e.title for e in store.goal_log("G-1")], ["new title", ""])
        indexes = {r[1] for r in store._conn.execute("PRAGMA index_list(goal_log)").fetchall()}
        self.assertIn("idx_goal_log_goal_id", indexes)

    def test_non_blank_scope_is_carried_over_under_its_own_heading(self):
        root = tempfile.mkdtemp()
        config = self._plant(root, [("G-1", "g", "out", "In: x")])

        self.assertEqual(
            SqliteStore(config).get_goal("G-1").description,
            "out\n\n## Scope (carried over)\n\nIn: x",
        )

    def test_empty_outcome_starts_at_the_first_appended_heading(self):
        root = tempfile.mkdtemp()
        config = self._plant(root, [("G-1", "g", "", "")], [("G-1", "q?", False)])

        self.assertEqual(
            SqliteStore(config).get_goal("G-1").description, "## Open questions\n\n- q?"
        )

    def test_each_goal_gets_its_own_result(self):
        root = tempfile.mkdtemp()
        config = self._plant(
            root, [("G-1", "a", "one", ""), ("G-2", "b", "two", "")], [("G-1", "q?", False)]
        )

        store = SqliteStore(config)

        self.assertEqual(store.get_goal("G-1").description, "one\n\n## Open questions\n\n- q?")
        self.assertEqual(store.get_goal("G-2").description, "two")

    def test_migration_is_idempotent(self):
        root = tempfile.mkdtemp()
        config = self._plant(root, [("G-1", "g", "out", "In: x")], [("G-1", "q?", False)])
        first = SqliteStore(config).get_goal("G-1")
        SqliteStore(config)._conn.close()

        self.assertEqual(SqliteStore(config).get_goal("G-1"), first)

    def test_fresh_store_has_the_new_shape_and_no_question_table(self):
        store = SqliteStore(self._config(tempfile.mkdtemp()))

        self.assertNotIn("goal_questions", self._tables(store))
        gid = store.create_goal("g", "d", "p")
        self.assertEqual(
            (store.get_goal(gid).description, store.get_goal(gid).project), ("d", "p")
        )
