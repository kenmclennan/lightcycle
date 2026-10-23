import datetime
import os
import sqlite3
import sys
import time
from contextlib import contextmanager

from lightcycle.adapters.fsio import DB_FILENAME
from lightcycle.adapters.sqlite.feedback import FeedbackAggregate
from lightcycle.adapters.sqlite.items import ItemsAggregate
from lightcycle.adapters.sqlite.projects import ProjectsAggregate
from lightcycle.adapters.sqlite.runs import RunsAggregate
from lightcycle.adapters.sqlite.shared import (
    _ITEM_COLUMNS,
    _STEP_COLUMNS,
)
from lightcycle.adapters.sqlite.steps import StepsAggregate
from lightcycle.adapters.sqlite.usage import UsageAggregate
from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE, LEGACY_KNOWLEDGE_WORKSPACE
from lightcycle.domain.money import Cost
from lightcycle.domain.work.forwarded_note import parse_forwarded
from lightcycle.domain.work import (
    Artifact, Item, Park, Step, derive_state,
    format_step_id,
)
from lightcycle.domain.workspace.isolation import refuses_live_store
from lightcycle.ports.store import (
    StoreError,
    StorePort,
)



class LiveStoreRefused(Exception):
    pass


class SchemaVersionRefused(Exception):
    pass


_SCHEMA_VERSION = 3
BUSY_TIMEOUT_MS = 30000
_LEGACY_LOG_TYPE = "log"
_LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES = "0.2.27"
_LAST_VERSION_ABLE_TO_MIGRATE_NODES_STORES = "0.6.263"


def _install_command(version):
    return "pipx install --force git+https://github.com/kenmclennan/lightcycle@v%s" % version

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT,
    state TEXT NOT NULL DEFAULT 'backlogged',
    repo TEXT,
    workflow TEXT,
    outcome TEXT,
    disposition TEXT,
    note TEXT,
    project TEXT,
    created_at TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    item TEXT NOT NULL,
    stage TEXT,
    pass_id TEXT,
    role TEXT,
    state TEXT NOT NULL DEFAULT 'ready',
    assignee TEXT,
    claim_epoch INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    outcome TEXT,
    notes TEXT,
    watched_step TEXT,
    park_reason TEXT,
    park_needs TEXT,
    park_tried TEXT,
    created_at TEXT,
    fired_at TEXT,
    closed_at TEXT,
    active_seconds REAL,
    usage_input_tokens INTEGER NOT NULL DEFAULT 0,
    usage_output_tokens INTEGER NOT NULL DEFAULT 0,
    usage_cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    usage_cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    usage_cost_usd REAL NOT NULL DEFAULT 0,
    usage_cost_basis TEXT,
    usage_rates_used TEXT,
    usage_thinking_tokens INTEGER,
    usage_api_calls INTEGER,
    turn_count INTEGER NOT NULL DEFAULT 0,
    previous_step TEXT,
    report TEXT,
    log_path TEXT
);

CREATE TABLE IF NOT EXISTS step_inputs (
    step TEXT PRIMARY KEY,
    frozen_at TEXT,
    body TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_steps_item ON steps(item);
CREATE INDEX IF NOT EXISTS idx_steps_state ON steps(state);
CREATE INDEX IF NOT EXISTS idx_steps_stage ON steps(stage);
CREATE INDEX IF NOT EXISTS idx_steps_outcome ON steps(outcome);

CREATE TABLE IF NOT EXISTS step_tool_usage (
    step  TEXT NOT NULL,
    tool  TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (step, tool)
);

CREATE INDEX IF NOT EXISTS idx_step_tool_usage_tool ON step_tool_usage(tool);

CREATE TABLE IF NOT EXISTS step_gh_calls (
    spawnid TEXT PRIMARY KEY,
    step    TEXT NOT NULL,
    calls   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_step_gh_calls_step ON step_gh_calls(step);

CREATE TABLE IF NOT EXISTS usage_backfill_log (
    log_file    TEXT PRIMARY KEY,
    step        TEXT,
    ingested_at TEXT,
    had_result_line INTEGER
);

CREATE TABLE IF NOT EXISTS usage_accrual_state (
    spawnid              TEXT PRIMARY KEY,
    log_file             TEXT NOT NULL,
    offset                INTEGER NOT NULL,
    message_ids           TEXT NOT NULL,
    pending_tool_use       TEXT NOT NULL,
    posted_turn_count      INTEGER NOT NULL DEFAULT 0,
    posted_tool_usage      TEXT NOT NULL,
    posted_input_tokens    INTEGER NOT NULL DEFAULT 0,
    posted_output_tokens   INTEGER NOT NULL DEFAULT 0,
    posted_cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    posted_cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    posted_cost_usd         REAL NOT NULL DEFAULT 0.0
);


CREATE TABLE IF NOT EXISTS deps (
    node_id TEXT NOT NULL,
    blocked_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deps_task_id ON deps(node_id);

CREATE TABLE IF NOT EXISTS artifacts (
    item_id TEXT NOT NULL,
    atype TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT,
    internal INTEGER NOT NULL DEFAULT 0,
    kind TEXT
);
CREATE INDEX IF NOT EXISTS idx_artifacts_item ON artifacts(item_id);

CREATE TABLE IF NOT EXISTS labels (
    node_id TEXT NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    namespace TEXT PRIMARY KEY,
    next INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    node_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    state TEXT NOT NULL,
    ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_node_id_seq ON history(node_id, seq);

CREATE TABLE IF NOT EXISTS passes (
    id        TEXT PRIMARY KEY,
    item      TEXT NOT NULL,
    n         INTEGER NOT NULL,
    state     TEXT NOT NULL DEFAULT 'open',
    opened_at TEXT,
    closed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_passes_item ON passes(item);

CREATE TABLE IF NOT EXISTS phase_runs (
    id          TEXT PRIMARY KEY,
    item        TEXT NOT NULL,
    pass_id     TEXT NOT NULL,
    phase       TEXT,
    branch      TEXT,
    pr          TEXT,
    content_pin TEXT,
    comments_dispatched_through TEXT,
    comments_handled_through    TEXT,
    state       TEXT NOT NULL DEFAULT 'open',
    opened_at   TEXT,
    closed_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_phase_runs_item ON phase_runs(item);

CREATE TABLE IF NOT EXISTS projects (
    identity   TEXT PRIMARY KEY,
    shortcode  TEXT,
    local_path TEXT,
    remote     TEXT,
    facets     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS schedule_run_requests (
    schedule_id TEXT PRIMARY KEY,
    requested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summaries (
    day TEXT PRIMARY KEY,
    summary TEXT,
    generated_at TEXT,
    summarized_count INTEGER NOT NULL DEFAULT 0,
    dirty_since TEXT,
    step_id TEXT,
    spawn_count INTEGER
);

CREATE TABLE IF NOT EXISTS held_comments (
    run_id     TEXT NOT NULL,
    key        TEXT NOT NULL,
    author     TEXT NOT NULL,
    body       TEXT NOT NULL,
    path       TEXT,
    line       INTEGER,
    created_at REAL NOT NULL,
    state      TEXT NOT NULL DEFAULT 'held',
    item_id    TEXT,
    step_id    TEXT,
    decided_at TEXT,
    PRIMARY KEY (run_id, key)
);
CREATE INDEX IF NOT EXISTS idx_held_comments_step_id ON held_comments(step_id);
CREATE INDEX IF NOT EXISTS idx_held_comments_run_id_state ON held_comments(run_id, state);

CREATE TABLE IF NOT EXISTS pr_feedback_cutoffs (
    pr          TEXT PRIMARY KEY,
    cutoff      REAL NOT NULL,
    cutoff_head TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pr_pool_updates (
    pr         TEXT NOT NULL,
    head_sha   TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (pr, head_sha)
);
"""




_STEP_LABEL_COLUMNS = {"for": "role", "stage": "stage"}
_ITEM_LABEL_COLUMNS = {"project": "project"}



class _ErrorTranslatingConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, *args, **kwargs):
        return self._guarded(self._conn.execute, *args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._guarded(self._conn.executescript, *args, **kwargs)

    def commit(self, *args, **kwargs):
        return self._guarded(self._conn.commit, *args, **kwargs)

    def rollback(self, *args, **kwargs):
        return self._guarded(self._conn.rollback, *args, **kwargs)

    def _guarded(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except sqlite3.Error as e:
            raise StoreError(str(e)) from e


class SqliteStore(
    ItemsAggregate, StepsAggregate, RunsAggregate, UsageAggregate, FeedbackAggregate,
    ProjectsAggregate, StorePort,
):
    def __init__(self, config, now=None, package_root=None, default_data_root=None):
        self._config = config
        self._now = now or (lambda: datetime.datetime.now().astimezone().isoformat())
        self._tx_depth = 0
        self._refuse_live_store_from_worktree(package_root, default_data_root)
        self._db_path = os.path.join(config.data_root(), DB_FILENAME)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        try:
            self._conn = _ErrorTranslatingConnection(sqlite3.connect(self._db_path, timeout=BUSY_TIMEOUT_MS / 1000))
        except sqlite3.Error as e:
            raise StoreError(str(e)) from e
        self._conn.execute("PRAGMA busy_timeout=%d" % BUSY_TIMEOUT_MS)
        self._enable_wal()
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self.last_migration = None
        version = self._apply_schema_version_floor()
        self._migrate_add_missing_columns()
        self._migrate_drop_step_reflection_column()
        self._migrate_drop_step_title_column()
        self._migrate_abandoned_disposition_value()
        self._migrate_rename_knowledge_project()
        self._migrate_drop_legacy_artifact_types()
        if version == 1:
            self._migrate_schema_1_to_2()
        self._migrate_drop_goal_tables()
        if version in (1, 2):
            self._conn.execute("PRAGMA user_version = %d" % _SCHEMA_VERSION)
        self._commit()

    def close(self):
        self._conn.close()

    def _enable_wal(self):
        deadline = time.monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                return
            except StoreError as e:
                if "locked" not in str(e) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _commit(self):
        if self._tx_depth == 0:
            self._conn.commit()

    @contextmanager
    def transaction(self):
        self._tx_depth += 1
        try:
            yield
        except BaseException:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._conn.rollback()
            raise
        else:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._conn.commit()

    def _refuse_live_store_from_worktree(self, package_root, default_data_root):
        pkg = package_root if package_root is not None else self._config.package_root()
        live_root = (
            default_data_root if default_data_root is not None
            else self._config.default_data_root()
        )
        if refuses_live_store(pkg, live_root, self._config.data_root()):
            raise LiveStoreRefused(
                "running from a worktree checkout; refusing the live store. "
                "Branch code verifies via tests against a temp store; set LC_HOME to point elsewhere."
            )

    def _apply_schema_version_floor(self):
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0 and self._is_legacy_store():
            raise SchemaVersionRefused(
                "store predates the schema-version floor and cannot be opened by "
                "this engine; migrate it with `%s` first, then reopen."
                % _install_command(_LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES)
            )
        if self._has_table("nodes"):
            raise SchemaVersionRefused(
                "store still carries the pre-split nodes table and cannot be opened by "
                "this engine; migrate it with `%s` first, then reopen."
                % _install_command(_LAST_VERSION_ABLE_TO_MIGRATE_NODES_STORES)
            )
        if version >= _SCHEMA_VERSION:
            return version
        if version == 0:
            self._conn.execute("PRAGMA user_version = %d" % _SCHEMA_VERSION)
            return version
        if version in (1, 2):
            return version
        raise SchemaVersionRefused(
            "store is stamped at schema version %d, below this engine's floor of "
            "%d; migrate it with `%s` first, then reopen."
            % (version, _SCHEMA_VERSION, _install_command(_LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES))
        )

    def _migrate_schema_1_to_2(self):
        matched = 0
        unmatched = 0
        rows = self._conn.execute(
            "SELECT id, item, notes, created_at FROM steps WHERE notes LIKE '%from %'"
        ).fetchall()
        for step_id, item, notes, created_at in rows:
            forwarded = parse_forwarded(notes)
            if forwarded is None:
                continue
            writer = self._forwarded_writer(item, forwarded, created_at)
            if writer is None:
                unmatched += 1
                continue
            matched += 1
            self._conn.execute(
                "UPDATE steps SET report = ? WHERE id = ? AND (report IS NULL OR report = '')",
                (forwarded.text, writer),
            )
            self._conn.execute(
                "UPDATE steps SET previous_step = ? WHERE id = ? AND previous_step IS NULL",
                (writer, step_id),
            )
        logs = self._backfill_log_paths()
        self.last_migration = {"matched": matched, "unmatched": unmatched, "logs": logs}
        self._conn.execute("PRAGMA user_version = 2")
        sys.stderr.write(
            "schema 2: backfilled %d reports (%d unmatched), copied %d logs\n"
            % (matched, unmatched, logs)
        )

    def _forwarded_writer(self, item, forwarded, receiver_created_at):
        candidates = self._conn.execute(
            "SELECT id, closed_at FROM steps WHERE item = ? AND stage = ? AND outcome = ? "
            "AND state = 'done'",
            (item, forwarded.stage, forwarded.outcome),
        ).fetchall()
        eligible = [
            (closed_at or "", sid) for sid, closed_at in candidates
            if closed_at and (not receiver_created_at or closed_at <= receiver_created_at)
        ]
        if not eligible:
            return None
        return max(eligible)[1]

    def _backfill_log_paths(self):
        copied = 0
        step_ids = {r[0] for r in self._conn.execute("SELECT id FROM steps").fetchall()}
        latest = {}
        for node_id, value in self._conn.execute(
            "SELECT item_id, value FROM artifacts WHERE atype = ? ORDER BY rowid",
            (_LEGACY_LOG_TYPE,),
        ).fetchall():
            latest[node_id] = value
        for node_id, value in latest.items():
            if node_id in step_ids:
                copied += self._conn.execute(
                    "UPDATE steps SET log_path = ? WHERE id = ?", (value, node_id)
                ).rowcount
        for node_id, value in latest.items():
            if node_id in step_ids:
                continue
            oldest = self._conn.execute(
                "SELECT id FROM steps WHERE item = ? ORDER BY created_at, rowid LIMIT 1",
                (node_id,),
            ).fetchone()
            if oldest is None:
                continue
            copied += self._conn.execute(
                "UPDATE steps SET log_path = ? WHERE id = ? AND log_path IS NULL",
                (value, oldest[0]),
            ).rowcount
        return copied

    def _is_legacy_store(self):
        if not self._has_table("nodes"):
            return False
        node_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        if "status" in node_cols or "workflow" not in node_cols:
            return True
        history_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(history)").fetchall()}
        if "ts" not in history_cols:
            return True
        return "status" in history_cols and "state" not in history_cols

    _ADDED_COLUMNS = {
        "items": (
            ("disposition", "TEXT"),
            ("note", "TEXT"),
        ),
        "phase_runs": (
            ("comments_dispatched_through", "TEXT"),
            ("comments_handled_through", "TEXT"),
        ),
        "steps": (
            ("active_seconds", "REAL"),
            ("usage_input_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("usage_output_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("usage_cache_read_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("usage_cache_creation_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("usage_cost_usd", "REAL NOT NULL DEFAULT 0"),
            ("usage_cost_basis", "TEXT"),
            ("usage_rates_used", "TEXT"),
            ("usage_thinking_tokens", "INTEGER"),
            ("usage_api_calls", "INTEGER"),
            ("turn_count", "INTEGER NOT NULL DEFAULT 0"),
            ("claim_epoch", "INTEGER NOT NULL DEFAULT 0"),
            ("previous_step", "TEXT"),
            ("report", "TEXT"),
            ("log_path", "TEXT"),
        ),
        "usage_backfill_log": (
            ("had_result_line", "INTEGER"),
        ),
        "projects": (
            ("facets", "TEXT NOT NULL DEFAULT ''"),
        ),
    }

    def _migrate_add_missing_columns(self):
        for table, columns in self._ADDED_COLUMNS.items():
            if not self._has_table(table):
                continue
            present = {
                r[1] for r in self._conn.execute("PRAGMA table_info(%s)" % table).fetchall()
            }
            for name, decl in columns:
                if name not in present:
                    self._conn.execute(
                        "ALTER TABLE %s ADD COLUMN %s %s" % (table, name, decl)
                    )

    def _migrate_drop_step_reflection_column(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(steps)").fetchall()}
        if "reflection" in cols:
            self._conn.execute("ALTER TABLE steps DROP COLUMN reflection")

    def _migrate_drop_step_title_column(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(steps)").fetchall()}
        if "title" in cols:
            self._conn.execute("UPDATE steps SET title = ''")
            self._conn.execute("ALTER TABLE steps DROP COLUMN title")

    def _migrate_rename_knowledge_project(self):
        self._conn.execute(
            "UPDATE projects SET identity = ? WHERE identity = ? "
            "AND NOT EXISTS (SELECT 1 FROM projects WHERE identity = ?)",
            (GUIDANCE_WORKSPACE, LEGACY_KNOWLEDGE_WORKSPACE, GUIDANCE_WORKSPACE),
        )

    def _migrate_drop_legacy_artifact_types(self):
        self._conn.execute(
            "DELETE FROM artifacts WHERE atype IN ('brief', 'design', 'backlog')"
        )

    def _migrate_abandoned_disposition_value(self):
        self._conn.execute(
            "UPDATE items SET disposition = 'abandoned' WHERE disposition = 'aborted'"
        )

    def _migrate_drop_goal_tables(self):
        for table in ("goal_items", "goal_log", "goals", "goal_questions"):
            self._conn.execute("DROP TABLE IF EXISTS %s" % table)
        if self._has_table("counters"):
            self._conn.execute("DELETE FROM counters WHERE namespace = 'goal'")

    def _has_table(self, name):
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone() is not None

    def _row_to_step(self, row, blocked_by):
        d = dict(zip(_STEP_COLUMNS, row))
        deps = len(blocked_by)
        return Step(
            id=d["id"],
            item=d["item"],
            stage=d["stage"],
            pass_id=d["pass_id"],
            role=d["role"],
            state=derive_state("step", d["state"] == "done", d["assignee"], deps, d["role"], []),
            claimed_by=d["assignee"],
            model=d["model"],
            outcome=d["outcome"],
            notes=d["notes"],
            watched_step=d["watched_step"],
            park=Park(reason=d["park_reason"], needs=d["park_needs"], tried=d["park_tried"]),
            deps=deps,
            blocked_by=blocked_by,
            created_at=d["created_at"],
            fired_at=d["fired_at"],
            closed_at=d["closed_at"],
            active_seconds=d["active_seconds"],
            usage_input_tokens=d["usage_input_tokens"],
            usage_output_tokens=d["usage_output_tokens"],
            usage_cache_read_tokens=d["usage_cache_read_tokens"],
            usage_cache_creation_tokens=d["usage_cache_creation_tokens"],
            usage_cost_usd=Cost.from_usd(d["usage_cost_usd"]),
            usage_cost_basis=d["usage_cost_basis"],
            usage_rates_used=d["usage_rates_used"],
            usage_thinking_tokens=d["usage_thinking_tokens"],
            usage_api_calls=d["usage_api_calls"],
            turn_count=d["turn_count"],
            previous_step=d["previous_step"],
            report=d["report"],
            log_path=d["log_path"],
        )

    def _row_to_item(self, row, artifacts, blocked_by, child_states):
        d = dict(zip(_ITEM_COLUMNS, row))
        return Item(
            id=d["id"],
            artifacts=tuple(artifacts),
            title=d["title"],
            description=d["description"],
            state=derive_state(
                "item", d["state"] == "done", None, bool(blocked_by), None, child_states
            ),
            repo=d["repo"],
            project=d["project"],
            workflow=d["workflow"],
            outcome=d["outcome"],
            disposition=d["disposition"],
            note=d["note"],
            deps=len(blocked_by),
            blocked_by=blocked_by,
            created_at=d["created_at"],
            closed_at=d["closed_at"],
        )

    def _unresolved_deps(self, ids):
        if not ids:
            return {}
        placeholders = ", ".join("?" * len(ids))
        out = {}
        for node_id, blocker_id in self._conn.execute(
            "SELECT d.node_id, d.blocked_by FROM deps d "
            "LEFT JOIN steps s ON s.id = d.blocked_by "
            "LEFT JOIN items i ON i.id = d.blocked_by "
            "WHERE COALESCE(s.state, i.state, 'ready') != 'done' AND d.node_id IN (%s)"
            % placeholders,
            ids,
        ).fetchall():
            out.setdefault(node_id, []).append(blocker_id)
        return out

    def _child_states_of(self, item_ids):
        if not item_ids:
            return {}
        placeholders = ", ".join("?" * len(item_ids))
        rows = self._conn.execute(
            "SELECT id, item, state, assignee, role FROM steps WHERE item IN (%s)" % placeholders,
            item_ids,
        ).fetchall()
        deps = self._unresolved_deps([r[0] for r in rows])
        out = {}
        for step_id, item, state, assignee, role in rows:
            out.setdefault(item, []).append(
                derive_state("step", state == "done", assignee, len(deps.get(step_id, [])), role, [])
            )
        return out

    def _rows_to_steps(self, rows):
        if not rows:
            return []
        deps = self._unresolved_deps([r[0] for r in rows])
        return [self._row_to_step(row, deps.get(row[0], [])) for row in rows]

    def _rows_to_items(self, rows):
        if not rows:
            return []
        ids = [r[0] for r in rows]
        placeholders = ", ".join("?" * len(ids))
        artifacts_by_id = {}
        for item_id, atype, value, label, internal, kind in self._conn.execute(
            "SELECT item_id, atype, value, label, internal, kind FROM artifacts "
            "WHERE item_id IN (%s) ORDER BY rowid" % placeholders,
            ids,
        ).fetchall():
            artifacts_by_id.setdefault(item_id, []).append(
                Artifact(type=atype, value=value, label=label, internal=bool(internal), kind=kind)
            )
        deps = self._unresolved_deps(ids)
        children = self._child_states_of(ids)
        return [
            self._row_to_item(
                row, artifacts_by_id.get(row[0], []), deps.get(row[0], []),
                children.get(row[0], []),
            )
            for row in rows
        ]

    def _select_steps(self, where, params=(), suffix=""):
        sql = "SELECT %s FROM steps" % ", ".join(_STEP_COLUMNS)
        if where:
            sql += " WHERE " + where
        if suffix:
            sql += " " + suffix
        return self._rows_to_steps(self._conn.execute(sql, params).fetchall())

    def _select_items(self, where, params=(), suffix=""):
        sql = "SELECT %s FROM items" % ", ".join(_ITEM_COLUMNS)
        if where:
            sql += " WHERE " + where
        if suffix:
            sql += " " + suffix
        return self._rows_to_items(self._conn.execute(sql, params).fetchall())

    def _mint_id(self, item, shortcode=None):
        if item is None and not shortcode:
            raise ValueError("create_item needs an explicit shortcode or id; nothing fills one in")
        namespace = item if item is not None else shortcode
        row = self._conn.execute(
            "INSERT INTO counters (namespace, next) VALUES (?, 2) "
            "ON CONFLICT(namespace) DO UPDATE SET next = next + 1 "
            "RETURNING next - 1",
            (namespace,),
        ).fetchone()
        n = row[0]
        if item is None:
            return "%s-%d" % (shortcode, n)
        return format_step_id(item, n)

    def _mint_or_adopt(self, explicit_id, item, shortcode=None):
        if explicit_id is None:
            return self._mint_id(item, shortcode)
        exists = self._conn.execute(
            "SELECT 1 FROM steps WHERE id = ? UNION SELECT 1 FROM items WHERE id = ?",
            (explicit_id, explicit_id),
        ).fetchone()
        if exists:
            raise ValueError("id already in use: %s" % explicit_id)
        return explicit_id

    def _table_of(self, tid):
        row = self._conn.execute("SELECT 1 FROM steps WHERE id = ?", (tid,)).fetchone()
        return "steps" if row else "items"

    def _apply_label(self, tid, label, value):
        prefix, sep, val = label.partition(":")
        if not sep:
            return False
        table = self._table_of(tid)
        column = (_STEP_LABEL_COLUMNS if table == "steps" else _ITEM_LABEL_COLUMNS).get(prefix)
        if column:
            self._conn.execute(
                "UPDATE %s SET %s = ? WHERE id = ?" % (table, column),
                (val if value else None, tid),
            )
            return True
        return False

    def _record_history(self, tid, state):
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) FROM history WHERE node_id = ?", (tid,)
        ).fetchone()
        self._conn.execute(
            "INSERT INTO history (node_id, seq, state, ts) VALUES (?, ?, ?, ?)",
            (tid, row[0] + 1, str(state), self._now()),
        )

























    def ensure_ready(self):
        pass


















































































































