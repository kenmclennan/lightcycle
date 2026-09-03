import datetime
import os
import sqlite3

from lightcycle.domain.runs import Pass, PhaseRun, RunState, pass_id, run_id
from lightcycle.domain.work import (
    Artifact, Item, NodeView, Park, State, Step, default_kind_for, derive_state,
    merge_condition_note,
)
from lightcycle.domain.workspace.isolation import refuses_live_store
from lightcycle.ports.store import (
    ItemTextRow,
    NodeNotFoundError,
    ProjectEntry,
    ProjectResolutionError,
    StorePort,
)

_DB_FILENAME = "store.db"


class LiveStoreRefused(Exception):
    pass


class SchemaVersionRefused(Exception):
    pass


_SCHEMA_VERSION = 1
_LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES = "0.2.27"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
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

CREATE TABLE IF NOT EXISTS steps (
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
    closed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_steps_item ON steps(item);
CREATE INDEX IF NOT EXISTS idx_steps_state ON steps(state);
CREATE INDEX IF NOT EXISTS idx_steps_stage ON steps(stage);


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
    remote     TEXT
);
"""

_ITEM_COLUMNS = (
    "id", "title", "description", "state", "repo", "workflow", "outcome", "project",
    "created_at", "closed_at",
)

_STEP_COLUMNS = (
    "id", "item", "title", "stage", "pass_id", "role", "state", "assignee", "model",
    "outcome", "notes", "reflection", "watched_step",
    "park_reason", "park_needs", "park_tried",
    "created_at", "fired_at", "closed_at",
)

_PARK_COLUMNS = {"needs": "park_needs", "reason": "park_reason", "tried": "park_tried"}

_STEP_LABEL_COLUMNS = {"for": "role", "step": "stage"}
_ITEM_LABEL_COLUMNS = {"project": "project"}

_RUN_SELECT = (
    "SELECT id, item, pass_id, phase, branch, pr, content_pin, "
    "comments_dispatched_through, comments_handled_through, state, opened_at, closed_at "
    "FROM phase_runs"
)


_LEGACY_STEP_NAMES = (
    "build", "review", "review-plan", "develop", "watch-pr", "ready-merge",
    "resolve", "conflict-review",
)
_LEGACY_ROLE_NAMES = ("coder", "reviewer", "auditor", "watch-pr", "resolve")

_INTERNAL_ARTIFACT_TYPES = (
    "reflection", "resolves", "resolved-by", "watched-step",
    "feedback-spawned-through", "feedback-watermark",
)


class SqliteStore(StorePort):
    def __init__(self, config, now=None, package_root=None, default_data_root=None):
        self._config = config
        self._now = now or (lambda: datetime.datetime.now().isoformat())
        self._refuse_live_store_from_worktree(package_root, default_data_root)
        self._db_path = os.path.join(config.data_root(), _DB_FILENAME)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._apply_schema_version_floor()
        if self._has_table("nodes"):
            self._migrate_close_reason_to_outcome()
            self._migrate_artifact_fields()
            self._migrate_resume_fields()
            self._migrate_detach_items_from_themes()
            self._migrate_collapse_step_roles()
            self._migrate_brief_artifacts_into_description()
            self._migrate_phase_artifacts_into_runs()
            self._migrate_split_nodes()
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
        if version >= _SCHEMA_VERSION:
            return
        if version == 0:
            if self._is_legacy_store():
                raise SchemaVersionRefused(
                    "store predates the schema-version floor and cannot be opened by "
                    "this engine; migrate it with lightcycle %s first, then reopen."
                    % _LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES
                )
            self._conn.execute("PRAGMA user_version = %d" % _SCHEMA_VERSION)
            return
        raise SchemaVersionRefused(
            "store is stamped at schema version %d, below this engine's floor of "
            "%d; migrate it with lightcycle %s first, then reopen."
            % (version, _SCHEMA_VERSION, _LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES)
        )

    def _is_legacy_store(self):
        if not self._has_table("nodes"):
            return False
        node_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        if "status" in node_cols or "workflow" not in node_cols:
            return True
        history_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(history)").fetchall()}
        if "ts" not in history_cols:
            return True
        if "status" in history_cols and "state" not in history_cols:
            return True
        q = "SELECT 1 FROM nodes WHERE step IN (%s) OR role IN (%s) LIMIT 1" % (
            ",".join("?" * len(_LEGACY_STEP_NAMES)),
            ",".join("?" * len(_LEGACY_ROLE_NAMES)),
        )
        return self._conn.execute(q, _LEGACY_STEP_NAMES + _LEGACY_ROLE_NAMES).fetchone() is not None

    def _migrate_close_reason_to_outcome(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        if "close_reason" in cols and "outcome" not in cols:
            self._conn.execute("ALTER TABLE nodes RENAME COLUMN close_reason TO outcome")

    def _migrate_artifact_fields(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(artifacts)").fetchall()}
        if "internal" not in cols:
            self._conn.execute(
                "ALTER TABLE artifacts ADD COLUMN internal INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.execute(
                "UPDATE artifacts SET internal = 1 WHERE atype IN (%s)"
                % ",".join("?" * len(_INTERNAL_ARTIFACT_TYPES)),
                _INTERNAL_ARTIFACT_TYPES,
            )
        if "kind" not in cols:
            self._conn.execute("ALTER TABLE artifacts ADD COLUMN kind TEXT")
            atypes = [
                r[0] for r in self._conn.execute("SELECT DISTINCT atype FROM artifacts").fetchall()
            ]
            for atype in atypes:
                self._conn.execute(
                    "UPDATE artifacts SET kind = ? WHERE atype = ?",
                    (default_kind_for(atype), atype),
                )

    def _migrate_resume_fields(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        for col in ("branch", "pr", "reason", "tried", "pass_id"):
            if col not in cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN %s TEXT" % col)

    def _migrate_detach_items_from_themes(self):
        self._conn.execute(
            "UPDATE nodes SET parent = NULL WHERE type = 'item' AND parent IN "
            "(SELECT id FROM nodes WHERE type = 'theme')"
        )

    def _migrate_collapse_step_roles(self):
        self._conn.execute(
            "UPDATE nodes SET role = 'agent' "
            "WHERE type = 'step' AND role IS NOT NULL AND role NOT IN ('agent', 'human')"
        )

    def _migrate_brief_artifacts_into_description(self):
        self._conn.execute(
            "UPDATE nodes SET description = ("
            "  SELECT value FROM artifacts WHERE item_id = nodes.id AND atype = 'brief' LIMIT 1"
            ") WHERE (description IS NULL OR description = '') AND id IN ("
            "  SELECT item_id FROM artifacts WHERE atype = 'brief'"
            ")"
        )
        self._conn.execute("DELETE FROM artifacts WHERE atype = 'brief'")

    _STEP_FOLDED_ARTIFACTS = ("reflection", "watched-step")
    _RUN_FOLDED_ARTIFACTS = ("feedback-watermark", "feedback-spawned-through")

    def _has_table(self, name):
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone() is not None

    def _migrate_split_nodes(self):
        if not self._has_table("nodes"):
            return
        self._fold_comment_ledger_into_runs()
        step_folds = self._step_artifact_folds()
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()]
        rows = self._conn.execute("SELECT %s FROM nodes" % ", ".join(cols)).fetchall()
        for row in rows:
            d = dict(zip(cols, row))
            if d.get("type") == "item":
                self._conn.execute(
                    "INSERT OR IGNORE INTO items (id, title, description, state, repo, workflow, "
                    "outcome, project, created_at, closed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], d["title"], d["description"], d["state"],
                     self._repo_artifact_of(d["id"]), d.get("workflow"), d.get("outcome"),
                     d.get("project"), d.get("created_at"), d.get("closed_at")),
                )
            elif d.get("parent"):
                fold = step_folds.get(d["id"], {})
                self._conn.execute(
                    "INSERT OR IGNORE INTO steps (id, item, title, stage, pass_id, role, state, "
                    "assignee, model, outcome, notes, reflection, watched_step, "
                    "park_reason, park_needs, park_tried, created_at, fired_at, closed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (d["id"], d["parent"], d["title"], d.get("step"), d.get("pass_id"),
                     d.get("role"), d["state"], d.get("assignee"), d.get("model"),
                     d.get("outcome"), d.get("notes"), fold.get("reflection"),
                     fold.get("watched-step"), d.get("reason"), d.get("needs"), d.get("tried"),
                     d.get("created_at"), d.get("fired_at"), d.get("closed_at")),
                )
        self._conn.execute(
            "DELETE FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._STEP_FOLDED_ARTIFACTS)),
            self._STEP_FOLDED_ARTIFACTS,
        )
        self._conn.execute("DELETE FROM artifacts WHERE atype = 'repo'")
        self._conn.execute("DROP TABLE nodes")

    def _repo_artifact_of(self, item_id):
        row = self._conn.execute(
            "SELECT value FROM artifacts WHERE item_id = ? AND atype = 'repo' LIMIT 1", (item_id,)
        ).fetchone()
        return row[0] if row else None

    def _step_artifact_folds(self):
        folds = {}
        rows = self._conn.execute(
            "SELECT item_id, atype, value FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._STEP_FOLDED_ARTIFACTS)),
            self._STEP_FOLDED_ARTIFACTS,
        ).fetchall()
        for node_id, atype, value in rows:
            folds.setdefault(node_id, {})[atype] = value
        return folds

    def _fold_comment_ledger_into_runs(self):
        rows = self._conn.execute(
            "SELECT item_id, atype, value FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._RUN_FOLDED_ARTIFACTS)),
            self._RUN_FOLDED_ARTIFACTS,
        ).fetchall()
        for step_id, atype, value in rows:
            owner = self._conn.execute(
                "SELECT parent, step FROM nodes WHERE id = ?", (step_id,)
            ).fetchone()
            if not owner or not owner[0]:
                continue
            run = self._conn.execute(
                "SELECT id FROM phase_runs WHERE item = ? ORDER BY opened_at DESC LIMIT 1",
                (owner[0],),
            ).fetchone()
            if run is None:
                continue
            column = (
                "comments_handled_through" if atype == "feedback-watermark"
                else "comments_dispatched_through"
            )
            self._conn.execute(
                "UPDATE phase_runs SET %s = ? WHERE id = ?" % column, (value, run[0])
            )
        self._conn.execute(
            "DELETE FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._RUN_FOLDED_ARTIFACTS)),
            self._RUN_FOLDED_ARTIFACTS,
        )

    _FOLDED_ARTIFACTS = ("branch", "pr", "content-pin", "content-pin-pr", "phase-run")

    def _migrate_phase_artifacts_into_runs(self):
        rows = self._conn.execute(
            "SELECT item_id, atype, value, label FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._FOLDED_ARTIFACTS)),
            self._FOLDED_ARTIFACTS,
        ).fetchall()
        if not rows:
            return
        folded = {}
        for item, atype, value, label in rows:
            entry = folded.setdefault((item, label), {})
            if atype == "phase-run":
                try:
                    entry["n"] = int(value)
                except (TypeError, ValueError):
                    pass
            elif atype == "content-pin":
                entry["content_pin"] = value
            elif atype in ("branch", "pr"):
                entry[atype] = value
        now = self._now()
        for (item, phase), entry in folded.items():
            n = entry.get("n", 1)
            pid = pass_id(item, n)
            self._conn.execute(
                "INSERT OR IGNORE INTO passes (id, item, n, state, opened_at) "
                "VALUES (?, ?, ?, 'open', ?)",
                (pid, item, n, now),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO phase_runs "
                "(id, item, pass_id, phase, branch, pr, content_pin, state, opened_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                (run_id(pid, phase), item, pid, phase, entry.get("branch"), entry.get("pr"),
                 entry.get("content_pin"), now),
            )
        self._conn.execute(
            "DELETE FROM artifacts WHERE atype IN (%s)"
            % ",".join("?" * len(self._FOLDED_ARTIFACTS)),
            self._FOLDED_ARTIFACTS,
        )

    def _row_to_step(self, row, blocked_by):
        d = dict(zip(_STEP_COLUMNS, row))
        deps = len(blocked_by)
        return Step(
            id=d["id"],
            item=d["item"],
            title=d["title"],
            stage=d["stage"],
            pass_id=d["pass_id"],
            role=d["role"],
            state=derive_state("step", d["state"] == "done", d["assignee"], deps, []),
            claimed_by=d["assignee"],
            model=d["model"],
            outcome=d["outcome"],
            notes=d["notes"],
            reflection=d["reflection"],
            watched_step=d["watched_step"],
            park=Park(reason=d["park_reason"], needs=d["park_needs"], tried=d["park_tried"]),
            deps=deps,
            blocked_by=blocked_by,
            created_at=d["created_at"],
            fired_at=d["fired_at"],
            closed_at=d["closed_at"],
        )

    def _row_to_item(self, row, artifacts, blocked_by, child_states):
        d = dict(zip(_ITEM_COLUMNS, row))
        return Item(
            id=d["id"],
            artifacts=tuple(artifacts),
            title=d["title"],
            description=d["description"],
            state=derive_state("item", d["state"] == "done", None, False, child_states),
            repo=d["repo"],
            project=d["project"],
            workflow=d["workflow"],
            outcome=d["outcome"],
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
            "SELECT %s FROM steps WHERE item IN (%s)"
            % (", ".join(_STEP_COLUMNS), placeholders),
            item_ids,
        ).fetchall()
        deps = self._unresolved_deps([r[0] for r in rows])
        out = {}
        for row in rows:
            step = self._row_to_step(row, deps.get(row[0], []))
            out.setdefault(step.item, []).append(step.state)
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

    def _mint_id(self, parent, shortcode=None):
        prefix = shortcode or self.shortcode()
        namespace = parent if parent is not None else prefix
        row = self._conn.execute(
            "SELECT next FROM counters WHERE namespace = ?", (namespace,)
        ).fetchone()
        n = row[0] if row else 1
        self._conn.execute(
            "INSERT INTO counters (namespace, next) VALUES (?, ?) "
            "ON CONFLICT(namespace) DO UPDATE SET next = excluded.next",
            (namespace, n + 1),
        )
        if parent is None:
            return "%s-%d" % (prefix, n)
        return "%s.%d" % (parent, n)

    def _mint_or_adopt(self, explicit_id, parent, shortcode=None):
        if explicit_id is None:
            return self._mint_id(parent, shortcode)
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

    def item_artifacts(self, item_id):
        rows = self._conn.execute(
            "SELECT atype, value, label, internal, kind FROM artifacts "
            "WHERE item_id = ? ORDER BY rowid",
            (item_id,),
        ).fetchall()
        return [
            Artifact(type=r[0], value=r[1], label=r[2], internal=bool(r[3]), kind=r[4])
            for r in rows
        ]

    def _set_repo(self, item_id, value):
        self._conn.execute("UPDATE items SET repo = ? WHERE id = ?", (value, item_id))
        self._conn.commit()

    def add_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            return self._set_repo(item_id, value)
        resolved_kind = kind if kind is not None else default_kind_for(atype)
        self._conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label, internal, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, atype, value, label, internal, resolved_kind),
        )
        self._conn.commit()

    def replace_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            return self._set_repo(item_id, value)
        resolved_kind = kind if kind is not None else default_kind_for(atype)
        if label is None:
            self._conn.execute(
                "DELETE FROM artifacts WHERE item_id = ? AND atype = ? AND label IS NULL",
                (item_id, atype),
            )
        else:
            self._conn.execute(
                "DELETE FROM artifacts WHERE item_id = ? AND atype = ? AND label = ?",
                (item_id, atype, label),
            )
        self._conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label, internal, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, atype, value, label, internal, resolved_kind),
        )
        self._conn.commit()

    def all_nodes(self):
        return self.all_steps() + self.all_items()

    def all_nodes_including_done(self):
        return self.all_steps_including_done() + self.all_items_including_done()

    def all_items(self):
        return self._select_items("state != 'done'")

    def all_items_including_done(self):
        return self._select_items("")

    def all_steps_including_done(self):
        return self._select_steps("")

    def item_text_rows(self):
        rows = self._conn.execute(
            "SELECT id, title, description, NULL FROM items"
        ).fetchall()
        return [ItemTextRow(*row) for row in rows]

    def all_steps(self):
        return self._select_steps("state != 'done'")

    def get_item(self, tid):
        rows = self._select_items("id = ?", (tid,))
        if not rows:
            raise NodeNotFoundError("unknown item '%s'" % tid)
        return rows[0]

    def get_step(self, tid):
        rows = self._select_steps("id = ?", (tid,))
        if not rows:
            raise NodeNotFoundError("unknown step '%s'" % tid)
        return rows[0]

    def get_node(self, tid):
        rows = self._select_steps("id = ?", (tid,))
        if rows:
            return rows[0]
        return self.get_item(tid)

    def node_view(self, tid):
        t = self.get_node(tid)
        item = getattr(t, "item", None)
        arts = self.item_artifacts(item) if item else t.artifacts
        return NodeView(step=t, item_artifacts=list(arts))

    def present_types(self, step):
        item = getattr(step, "item", None) or step.id
        present = {a.type for a in self.item_artifacts(item)}
        if self.get_item(item).repo:
            present.add("repo")
        for run in self.open_runs_of(item):
            if run.branch:
                present.add("branch")
            if run.pr:
                present.add("pr")
        return present

    def reassign(self, tid, role):
        cur = getattr(self.get_node(tid), "role", None)
        if cur and cur != role:
            self.label_remove(tid, "for:%s" % cur)
        self.label_add(tid, "for:%s" % role)
        self.update_state(tid, State.READY)
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_items(self):
        rows = self._conn.execute(
            "SELECT id, title, closed_at, outcome FROM items WHERE state = 'done'"
        ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "closed_at": r[2],
                "outcome": r[3],
                "artifacts": self.item_artifacts(r[0]),
            }
            for r in rows
        ]

    def shortcode(self):
        return self._config.shortcode()

    def export_rows(self):
        result = []
        for row in self._conn.execute(
            "SELECT %s FROM items ORDER BY rowid" % ", ".join(_ITEM_COLUMNS)
        ).fetchall():
            d = dict(zip(_ITEM_COLUMNS, row))
            result.append(dict(d, type="item", artifacts=[
                a.as_dict() for a in self.item_artifacts(d["id"])
            ], blocked_by=self._blockers_of(d["id"]), labels=self._labels_of(d["id"])))
        for row in self._conn.execute(
            "SELECT %s FROM steps ORDER BY rowid" % ", ".join(_STEP_COLUMNS)
        ).fetchall():
            d = dict(zip(_STEP_COLUMNS, row))
            result.append(dict(d, type="step", blocked_by=self._blockers_of(d["id"]),
                               labels=self._labels_of(d["id"])))
        return result

    def _blockers_of(self, tid):
        return [
            r[0] for r in self._conn.execute(
                "SELECT blocked_by FROM deps WHERE node_id = ?", (tid,)
            ).fetchall()
        ]

    def _labels_of(self, tid):
        return [
            r[0] for r in self._conn.execute(
                "SELECT label FROM labels WHERE node_id = ?", (tid,)
            ).fetchall()
        ]

    def ensure_store(self):
        pass

    def reclaim(self, tid):
        self.update_state(tid, State.READY)
        self.assign(tid, "")

    def note(self, tid, text):
        row = self._conn.execute("SELECT notes FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        combined = (row[0] + "\n" + text) if row[0] else text
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (combined, tid))
        self._conn.commit()

    def note_condition(self, tid, text):
        row = self._conn.execute("SELECT notes FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        combined = merge_condition_note(row[0] or "", text, self._now())
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (combined, tid))
        self._conn.commit()

    def set_notes(self, tid, text):
        row = self._conn.execute("SELECT 1 FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (text or None, tid))
        self._conn.commit()

    def reopen(self, tid):
        self._conn.execute(
            "UPDATE %s SET state = 'in_progress', outcome = NULL, closed_at = NULL "
            "WHERE id = ? AND state = 'done'" % self._table_of(tid),
            (tid,),
        )
        self._conn.commit()

    def close(self, tid, reason):
        self._conn.execute(
            "UPDATE %s SET state = 'done', outcome = ?, closed_at = ? "
            "WHERE id = ? AND state != 'done'" % self._table_of(tid),
            (reason, datetime.datetime.now().isoformat(), tid),
        )
        self._record_history(tid, State.DONE)
        self._conn.commit()

    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        expected = expected_assignee or ""
        cur = self._conn.execute(
            "UPDATE steps SET state = 'done', outcome = ?, closed_at = ? "
            "WHERE id = ? AND state != 'done' "
            "AND (? = '' OR COALESCE(assignee, '') = '' OR assignee = ?)",
            (outcome, datetime.datetime.now().isoformat(), step, expected, expected),
        )
        if cur.rowcount == 0:
            self._conn.rollback()
            return (False, None)
        try:
            self._record_history(step, State.DONE)
            new_id = None
            if next_step_spec is not None:
                new_id = self._insert_step_nocommit(**next_step_spec.as_kwargs())
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return (True, new_id)

    def disconnect(self):
        self._conn.close()

    def update_metadata(self, tid, meta):
        updates = {
            _PARK_COLUMNS[k]: v for k, v in meta.items() if k in _PARK_COLUMNS
        }
        if not updates:
            return
        set_clause = ", ".join("%s = ?" % k for k in updates)
        self._conn.execute(
            "UPDATE steps SET %s WHERE id = ?" % set_clause, (*updates.values(), tid)
        )
        self._conn.commit()

    def set_model(self, tid, model):
        self._conn.execute("UPDATE steps SET model = ? WHERE id = ?", (model, tid))
        self._conn.commit()

    def label_add(self, tid, label):
        if not self._apply_label(tid, label, True):
            exists = self._conn.execute(
                "SELECT 1 FROM labels WHERE node_id = ? AND label = ?", (tid, label)
            ).fetchone()
            if not exists:
                self._conn.execute(
                    "INSERT INTO labels (node_id, label) VALUES (?, ?)", (tid, label)
                )
        self._conn.commit()

    def label_remove(self, tid, label):
        if not self._apply_label(tid, label, False):
            self._conn.execute(
                "DELETE FROM labels WHERE node_id = ? AND label = ?", (tid, label)
            )
        self._conn.commit()

    def update_state(self, tid, state):
        self._conn.execute(
            "UPDATE %s SET state = ? WHERE id = ?" % self._table_of(tid), (str(state), tid)
        )
        self._record_history(tid, state)
        self._conn.commit()

    def assign(self, tid, assignee):
        self._conn.execute(
            "UPDATE steps SET assignee = ? WHERE id = ?", (assignee or None, tid)
        )
        self._conn.commit()

    def _dep_add_nocommit(self, node_id, blocked_by):
        exists = self._conn.execute(
            "SELECT 1 FROM deps WHERE node_id = ? AND blocked_by = ?", (node_id, blocked_by)
        ).fetchone()
        if not exists:
            self._conn.execute(
                "INSERT INTO deps (node_id, blocked_by) VALUES (?, ?)", (node_id, blocked_by)
            )

    def dep_add(self, node_id, blocked_by):
        self._dep_add_nocommit(node_id, blocked_by)
        self._conn.commit()

    def dep_remove(self, node_id, blocked_by):
        cur = self._conn.execute(
            "DELETE FROM deps WHERE node_id = ? AND blocked_by = ?", (node_id, blocked_by)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def ready_steps(self):
        return self._select_steps(
            "state = 'ready' AND NOT EXISTS ("
            "  SELECT 1 FROM deps d LEFT JOIN steps b ON b.id = d.blocked_by "
            "  LEFT JOIN items bi ON bi.id = d.blocked_by "
            "  WHERE d.node_id = steps.id AND COALESCE(b.state, bi.state, 'ready') != 'done'"
            ")"
        )

    def claim_ready(self, role):
        row = self._conn.execute(
            "SELECT id FROM steps WHERE state = 'ready' "
            "AND role = ? AND NOT EXISTS ("
            "  SELECT 1 FROM deps d LEFT JOIN steps b ON b.id = d.blocked_by "
            "  LEFT JOIN items bi ON bi.id = d.blocked_by "
            "  WHERE d.node_id = steps.id AND COALESCE(b.state, bi.state, 'ready') != 'done'"
            ") LIMIT 1",
            (role,),
        ).fetchone()
        if row is None:
            return None
        tid = row[0]
        assignee = self._config.spawn_id() or role
        cur = self._conn.execute(
            "UPDATE steps SET assignee = ?, state = 'in_progress' "
            "WHERE id = ? AND state = 'ready'",
            (assignee, tid),
        )
        if cur.rowcount == 0:
            self._conn.commit()
            return None
        self._record_history(tid, State.IN_PROGRESS)
        self._conn.commit()
        return self.get_node(tid)

    def _insert_step_nocommit(self, title, *, step=None, role=None, parent=None, deps=None,
                              description=None, id=None):
        tid = self._mint_or_adopt(id, parent)
        self._conn.execute(
            "INSERT INTO steps (id, item, title, stage, role, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'ready', ?)",
            (tid, parent, title, step, role, datetime.datetime.now().isoformat()),
        )
        if deps:
            for dep in deps:
                self._dep_add_nocommit(tid, dep)
        return tid

    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    description=None, id=None):
        tid = self._insert_step_nocommit(
            title, step=step, role=role, parent=parent, deps=deps,
            description=description, id=id)
        self._conn.commit()
        return tid

    def edit_node(self, tid, *, title=None, description=None, project=None,
                  workflow=None):
        table = self._table_of(tid)
        allowed = ("title",) if table == "steps" else (
            "title", "description", "project", "workflow"
        )
        updates = {}
        for key, value in (("title", title), ("description", description),
                           ("project", project), ("workflow", workflow)):
            if value is not None and key in allowed:
                updates[key] = value
        if updates:
            set_clause = ", ".join("%s = ?" % k for k in updates)
            self._conn.execute(
                "UPDATE %s SET %s WHERE id = ?" % (table, set_clause),
                (*updates.values(), tid),
            )
        self._conn.commit()
        return tid

    def create_item(self, title, description, *, project=None, workflow=None, id=None,
                    shortcode=None):
        tid = self._mint_or_adopt(id, None, shortcode=shortcode)
        self._conn.execute(
            "INSERT INTO items (id, title, description, state, project, workflow, created_at) "
            "VALUES (?, ?, ?, 'backlogged', ?, ?, ?)",
            (tid, title, description, project, workflow,
             datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def open_pass(self, item):
        row = self._conn.execute(
            "SELECT MAX(n) FROM passes WHERE item = ?", (item,)
        ).fetchone()
        n = (row[0] or 0) + 1
        pid = pass_id(item, n)
        self._conn.execute(
            "INSERT INTO passes (id, item, n, state, opened_at) VALUES (?, ?, ?, 'open', ?)",
            (pid, item, n, self._now()),
        )
        self._conn.commit()
        return pid

    def current_pass(self, item):
        row = self._conn.execute(
            "SELECT id, item, n, state, opened_at, closed_at FROM passes "
            "WHERE item = ? AND state = 'open' ORDER BY n DESC LIMIT 1",
            (item,),
        ).fetchone()
        return Pass(*row) if row else None

    def get_pass(self, pid):
        row = self._conn.execute(
            "SELECT id, item, n, state, opened_at, closed_at FROM passes WHERE id = ?", (pid,)
        ).fetchone()
        return Pass(*row) if row else None

    def passes_of(self, item):
        rows = self._conn.execute(
            "SELECT id, item, n, state, opened_at, closed_at FROM passes "
            "WHERE item = ? ORDER BY n",
            (item,),
        ).fetchall()
        return [Pass(*r) for r in rows]

    def close_pass(self, pid):
        self._conn.execute(
            "UPDATE passes SET state = 'closed', closed_at = ? WHERE id = ? AND state = 'open'",
            (self._now(), pid),
        )
        self._conn.commit()

    def open_run(self, item, pid, phase):
        rid = run_id(pid, phase)
        self._conn.execute(
            "INSERT OR IGNORE INTO phase_runs (id, item, pass_id, phase, state, opened_at) "
            "VALUES (?, ?, ?, ?, 'open', ?)",
            (rid, item, pid, phase, self._now()),
        )
        self._conn.commit()
        return rid

    def _run_row_to_record(self, row):
        return PhaseRun(*row)

    def get_run(self, rid):
        row = self._conn.execute(
            "%s WHERE id = ?" % _RUN_SELECT, (rid,)
        ).fetchone()
        return self._run_row_to_record(row) if row else None

    def current_run(self, item, phase):
        row = self._conn.execute(
            "%s WHERE item = ? AND phase IS ? AND state = 'open' "
            "ORDER BY opened_at DESC LIMIT 1" % _RUN_SELECT,
            (item, phase),
        ).fetchone()
        return self._run_row_to_record(row) if row else None

    def runs_of(self, item, pid=None):
        if pid is None:
            rows = self._conn.execute(
                "%s WHERE item = ? ORDER BY opened_at" % _RUN_SELECT, (item,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "%s WHERE item = ? AND pass_id = ? ORDER BY opened_at" % _RUN_SELECT, (item, pid)
            ).fetchall()
        return [self._run_row_to_record(r) for r in rows]

    def open_runs_of(self, item, pid=None):
        return [r for r in self.runs_of(item, pid) if r.is_open]

    def set_run_field(self, rid, **fields):
        allowed = {
            k: v for k, v in fields.items()
            if k in ("branch", "pr", "content_pin",
                     "comments_dispatched_through", "comments_handled_through")
        }
        if not allowed:
            return
        if "pr" in allowed and "content_pin" not in allowed:
            current = self.get_run(rid)
            if current is not None and current.pr != allowed["pr"]:
                allowed["content_pin"] = None
        clause = ", ".join("%s = ?" % k for k in allowed)
        self._conn.execute(
            "UPDATE phase_runs SET %s WHERE id = ?" % clause, (*allowed.values(), rid)
        )
        self._conn.commit()

    def close_run(self, rid, state=RunState.MERGED):
        self._conn.execute(
            "UPDATE phase_runs SET state = ?, closed_at = ? WHERE id = ? AND state = 'open'",
            (state, self._now(), rid),
        )
        self._conn.commit()

    def set_step_pass(self, tid, pid):
        self._conn.execute("UPDATE steps SET pass_id = ? WHERE id = ?", (pid, tid))
        self._conn.commit()

    def children(self, item_id):
        return self._select_steps("item = ?", (item_id,))

    def claimed_steps(self):
        return self._select_steps("state = 'in_progress'")

    def history(self, tid):
        rows = self._conn.execute(
            "SELECT state, ts FROM history WHERE node_id = ? ORDER BY seq ASC", (tid,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def nodes_closed_since(self, since_date):
        return self._select_steps(
            "state = 'done' AND substr(closed_at, 1, 10) >= ?", (since_date,)
        )

    def closed_unretroed_items(self):
        return self._select_items(
            "state = 'done' "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = 'retro-origin') "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = 'retroed')",
        )

    def last_n_closed_items(self, n):
        return self._select_items(
            "state = 'done'", params=(n,), suffix="ORDER BY closed_at DESC LIMIT ?"
        )

    def steps_at_step(self, step):
        return self._select_steps("stage = ?", (step,))

    def delete(self, tid):
        self._conn.execute("DELETE FROM steps WHERE id = ?", (tid,))
        self._conn.execute("DELETE FROM items WHERE id = ?", (tid,))
        self._conn.execute("DELETE FROM deps WHERE node_id = ? OR blocked_by = ?", (tid, tid))
        self._conn.execute("DELETE FROM artifacts WHERE item_id = ?", (tid,))
        self._conn.execute("DELETE FROM labels WHERE node_id = ?", (tid,))
        self._conn.execute("DELETE FROM history WHERE node_id = ?", (tid,))
        self._conn.commit()

    def add_project(self, identity, *, shortcode=None, local_path=None, remote=None):
        row = self._conn.execute(
            "SELECT shortcode, local_path, remote FROM projects WHERE identity = ?", (identity,)
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO projects (identity, shortcode, local_path, remote) "
                "VALUES (?, ?, ?, ?)",
                (identity, shortcode, local_path, remote),
            )
        else:
            merged = (
                shortcode if shortcode is not None else row[0],
                local_path if local_path is not None else row[1],
                remote if remote is not None else row[2],
            )
            self._conn.execute(
                "UPDATE projects SET shortcode = ?, local_path = ?, remote = ? WHERE identity = ?",
                (*merged, identity),
            )
        self._conn.commit()

    def get_project(self, identity):
        row = self._conn.execute(
            "SELECT identity, shortcode, local_path, remote FROM projects WHERE identity = ?",
            (identity,),
        ).fetchone()
        return ProjectEntry(*row) if row else None

    def list_projects(self):
        rows = self._conn.execute(
            "SELECT identity, shortcode, local_path, remote FROM projects ORDER BY identity"
        ).fetchall()
        return [ProjectEntry(*row) for row in rows]

    def remove_project(self, identity):
        cur = self._conn.execute("DELETE FROM projects WHERE identity = ?", (identity,))
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError("project not registered: %s" % identity)

    def _match_projects(self, ref):
        rows = self.list_projects()
        if "/" in ref:
            return [p for p in rows if p.identity == ref]
        return [p for p in rows if p.identity.rsplit("/", 1)[-1] == ref]

    def find_project(self, ref):
        matches = self._match_projects(ref)
        if not matches:
            raise ProjectResolutionError(
                "project '%s' is not registered - run `lc project add <owner/name> --path <dir>`"
                % ref
            )
        if len(matches) > 1:
            raise ProjectResolutionError(
                "project name '%s' is ambiguous - matches %s; use the full owner/name identity"
                % (ref, ", ".join(p.identity for p in matches))
            )
        return matches[0]

    def resolve_project_path(self, ref):
        if os.path.isabs(ref):
            return ref
        project = self.find_project(ref)
        if not project.local_path:
            raise ProjectResolutionError(
                "project '%s' is registered but has no local checkout - activate the item to "
                "clone it automatically, or run `lc project add %s --path <dir>` to point at an "
                "existing one" % (project.identity, project.identity)
            )
        return project.local_path
