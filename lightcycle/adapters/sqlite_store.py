import datetime
import os
import sqlite3

from lightcycle.domain.work import Artifact, Node, NodeView, State, derive_state
from lightcycle.domain.workspace.isolation import refuses_live_store
from lightcycle.ports.store import ProjectEntry, ProjectResolutionError, StorePort

_DB_FILENAME = "store.db"


class LiveStoreRefused(Exception):
    pass


class SchemaVersionRefused(Exception):
    pass


_SCHEMA_VERSION = 1
_LAST_VERSION_ABLE_TO_MIGRATE_PRE_FLOOR_STORES = "0.2.27"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
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
    outcome TEXT,
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

CREATE INDEX IF NOT EXISTS idx_nodes_state ON nodes(state);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);

CREATE TABLE IF NOT EXISTS deps (
    node_id TEXT NOT NULL,
    blocked_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deps_task_id ON deps(node_id);

CREATE TABLE IF NOT EXISTS artifacts (
    item_id TEXT NOT NULL,
    atype TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT
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

CREATE TABLE IF NOT EXISTS projects (
    identity   TEXT PRIMARY KEY,
    shortcode  TEXT,
    local_path TEXT,
    remote     TEXT
);
"""

_COLUMNS = (
    "id", "type", "title", "state", "step", "role", "parent", "project", "goal",
    "description", "notes", "outcome", "assignee", "since", "fired_at",
    "closed_at", "attention", "theme", "needs", "model", "workflow",
)

_METADATA_COLUMNS = ("theme", "needs", "since", "fired_at", "workflow")

_LABEL_COLUMNS = {"for": "role", "step": "step", "project": "project", "goal": "goal"}


_LEGACY_STEP_NAMES = (
    "build", "review", "review-plan", "develop", "watch-pr", "ready-merge",
    "resolve", "conflict-review",
)
_LEGACY_ROLE_NAMES = ("coder", "reviewer", "auditor", "watch-pr", "resolve")

_ID_BEARING_ARTIFACT_TYPES = {"branch", "pr", "spec", "resolves", "filed-from", "brief"}


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
        self._migrate_close_reason_to_outcome()
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

    def _row_to_node(self, row, artifacts, deps):
        d = dict(zip(_COLUMNS, row))
        closed = d["state"] == "done"
        if d["type"] == "step" or closed:
            state = derive_state(d["type"], closed, d["assignee"], deps, [])
        else:
            state = None
        return Node(
            id=d["id"],
            title=d["title"],
            type=d["type"],
            parent=d["parent"],
            role=d["role"],
            step=d["step"],
            state=state,
            project=d["project"],
            goal=d["goal"],
            artifacts=artifacts,
            description=d["description"],
            needs=d["needs"],
            outcome=d["outcome"],
            deps=deps,
            notes=d["notes"],
            claimed_by=d["assignee"],
            theme=d["parent"] if d["type"] == "item" else d["theme"],
            since=d["since"],
            fired_at=d["fired_at"],
            closed_at=d["closed_at"],
            attention=bool(d["attention"]),
            model=d["model"],
            workflow=d["workflow"],
        )

    def _rows_to_nodes(self, rows):
        if not rows:
            return []
        ids = [r[0] for r in rows]
        placeholders = ", ".join("?" * len(ids))

        artifacts_by_id = {}
        for item_id, atype, value, label in self._conn.execute(
            "SELECT item_id, atype, value, label FROM artifacts "
            "WHERE item_id IN (%s) ORDER BY rowid" % placeholders,
            ids,
        ).fetchall():
            artifacts_by_id.setdefault(item_id, []).append(
                Artifact(type=atype, value=value, label=label)
            )

        deps_by_id = dict(
            self._conn.execute(
                "SELECT d.node_id, COUNT(*) FROM deps d JOIN nodes t ON t.id = d.blocked_by "
                "WHERE t.state != 'done' AND d.node_id IN (%s) GROUP BY d.node_id"
                % placeholders,
                ids,
            ).fetchall()
        )

        nodes = [
            self._row_to_node(row, artifacts_by_id.get(row[0], []), deps_by_id.get(row[0], 0))
            for row in rows
        ]
        for node in nodes:
            if node.state is None:
                child_states = [c.state for c in self.children(node.id)]
                node.state = derive_state(
                    node.type, False, node.claimed_by, bool(node.deps), child_states
                )
        return nodes

    def _select(self, where, params=(), suffix=""):
        sql = "SELECT %s FROM nodes" % ", ".join(_COLUMNS)
        if where:
            sql += " WHERE " + where
        if suffix:
            sql += " " + suffix
        rows = self._conn.execute(sql, params).fetchall()
        return self._rows_to_nodes(rows)

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
            "SELECT 1 FROM nodes WHERE id = ?", (explicit_id,)
        ).fetchone()
        if exists:
            raise ValueError("id already in use: %s" % explicit_id)
        return explicit_id

    def _apply_label(self, tid, label, value):
        if label == "attention":
            self._conn.execute(
                "UPDATE nodes SET attention = ? WHERE id = ?", (1 if value else 0, tid)
            )
            return True
        prefix, sep, val = label.partition(":")
        column = _LABEL_COLUMNS.get(prefix) if sep else None
        if column:
            self._conn.execute(
                "UPDATE nodes SET %s = ? WHERE id = ?" % column, (val if value else None, tid)
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
            "SELECT atype, value, label FROM artifacts WHERE item_id = ? ORDER BY rowid",
            (item_id,),
        ).fetchall()
        return [Artifact(type=r[0], value=r[1], label=r[2]) for r in rows]

    def add_artifact(self, item_id, atype, value, label=None):
        self._conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label) VALUES (?, ?, ?, ?)",
            (item_id, atype, value, label),
        )
        self._conn.commit()

    def replace_artifact(self, item_id, atype, value, label=None):
        self._conn.execute(
            "DELETE FROM artifacts WHERE item_id = ? AND atype = ?",
            (item_id, atype),
        )
        self._conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label) VALUES (?, ?, ?, ?)",
            (item_id, atype, value, label),
        )
        self._conn.commit()

    def all_nodes(self):
        return self._select("state != 'done'")

    def all_nodes_including_done(self):
        return self._select("")

    def all_steps(self):
        return self._select("type = 'step' AND state != 'done'")

    def get_node(self, tid):
        row = self._conn.execute(
            "SELECT %s FROM nodes WHERE id = ?" % ", ".join(_COLUMNS), (tid,)
        ).fetchone()
        if row is None:
            raise KeyError("step not found: %s" % tid)
        return self._rows_to_nodes([row])[0]

    def node_view(self, tid):
        t = self.get_node(tid)
        arts = self.item_artifacts(t.parent) if t.parent else t.artifacts
        return NodeView(step=t, item_artifacts=list(arts))

    def present_types(self, step):
        item = step.parent or step.id
        return {a.type for a in self.item_artifacts(item)}

    def reassign(self, tid, role):
        cur = self.get_node(tid).role
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
            "SELECT id, title, closed_at, outcome FROM nodes "
            "WHERE type = 'item' AND state = 'done'"
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
        export_columns = _COLUMNS + ("created_at",)
        rows = self._conn.execute(
            "SELECT %s FROM nodes ORDER BY rowid" % ", ".join(export_columns)
        ).fetchall()
        result = []
        for row in rows:
            d = dict(zip(export_columns, row))
            tid = d["id"]
            artifacts = self.item_artifacts(tid)
            blocked_by = [
                r[0] for r in self._conn.execute(
                    "SELECT blocked_by FROM deps WHERE node_id = ?", (tid,)
                ).fetchall()
            ]
            labels = [
                r[0] for r in self._conn.execute(
                    "SELECT label FROM labels WHERE node_id = ?", (tid,)
                ).fetchall()
            ]
            result.append({
                "id": tid, "type": d["type"], "title": d["title"], "state": d["state"],
                "parent": d["parent"], "role": d["role"], "step": d["step"],
                "project": d["project"], "goal": d["goal"], "attention": bool(d["attention"]),
                "description": d["description"], "notes": d["notes"],
                "outcome": d["outcome"], "assignee": d["assignee"], "theme": d["theme"],
                "needs": d["needs"], "artifacts": [a.as_dict() for a in artifacts],
                "blocked_by": blocked_by, "labels": labels, "since": d["since"],
                "fired_at": d["fired_at"], "closed_at": d["closed_at"],
                "created_at": d["created_at"],
            })
        return result

    def ensure_store(self):
        pass

    def reclaim(self, tid):
        self.update_state(tid, State.READY)
        self.assign(tid, "")

    def note(self, tid, text):
        row = self._conn.execute("SELECT notes FROM nodes WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise KeyError("step not found: %s" % tid)
        combined = (row[0] + "\n" + text) if row[0] else text
        self._conn.execute("UPDATE nodes SET notes = ? WHERE id = ?", (combined, tid))
        self._conn.commit()

    def set_notes(self, tid, text):
        row = self._conn.execute("SELECT 1 FROM nodes WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise KeyError("step not found: %s" % tid)
        self._conn.execute("UPDATE nodes SET notes = ? WHERE id = ?", (text or None, tid))
        self._conn.commit()

    def close(self, tid, reason):
        self._conn.execute(
            "UPDATE nodes SET state = 'done', outcome = ?, closed_at = ? WHERE id = ? AND state != 'done'",
            (reason, datetime.datetime.now().isoformat(), tid),
        )
        self._record_history(tid, State.DONE)
        self._conn.commit()

    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        expected = expected_assignee or ""
        cur = self._conn.execute(
            "UPDATE nodes SET state = 'done', outcome = ?, closed_at = ? "
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
        updates = {k: v for k, v in meta.items() if k in _METADATA_COLUMNS}
        if not updates:
            return
        set_clause = ", ".join("%s = ?" % k for k in updates)
        self._conn.execute(
            "UPDATE nodes SET %s WHERE id = ?" % set_clause, (*updates.values(), tid)
        )
        self._conn.commit()

    def set_model(self, tid, model):
        self._conn.execute("UPDATE nodes SET model = ? WHERE id = ?", (model, tid))
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
        self._conn.execute("UPDATE nodes SET state = ? WHERE id = ?", (str(state), tid))
        self._record_history(tid, state)
        self._conn.commit()

    def assign(self, tid, assignee):
        self._conn.execute(
            "UPDATE nodes SET assignee = ? WHERE id = ?", (assignee or None, tid)
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
        return self._select(
            "type = 'step' AND state = 'ready' AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN nodes b ON b.id = d.blocked_by "
            "  WHERE d.node_id = nodes.id AND b.state != 'done'"
            ")"
        )

    def claim_ready(self, role):
        row = self._conn.execute(
            "SELECT id FROM nodes WHERE type = 'step' AND state = 'ready' "
            "AND role = ? AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN nodes b ON b.id = d.blocked_by "
            "  WHERE d.node_id = nodes.id AND b.state != 'done'"
            ") LIMIT 1",
            (role,),
        ).fetchone()
        if row is None:
            return None
        tid = row[0]
        assignee = self._config.spawn_id() or role
        cur = self._conn.execute(
            "UPDATE nodes SET assignee = ?, state = 'in_progress' "
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
                              project=None, goal=None, description=None, attention=False, id=None):
        tid = self._mint_or_adopt(id, parent)
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, state, step, role, parent, project, goal, "
            "description, attention, created_at) VALUES (?, 'step', ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, title, step, role, parent, project, goal, description,
             1 if attention else 0, datetime.datetime.now().isoformat()),
        )
        if deps:
            for dep in deps:
                self._dep_add_nocommit(tid, dep)
        return tid

    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False, id=None):
        tid = self._insert_step_nocommit(
            title, step=step, role=role, parent=parent, deps=deps, project=project,
            goal=goal, description=description, attention=attention, id=id)
        self._conn.commit()
        return tid

    def _is_referenceless(self, tid):
        if any(c.type == "step" for c in self.children(tid)):
            return False
        return not any(a.type in _ID_BEARING_ARTIFACT_TYPES for a in self.item_artifacts(tid))

    def _rename_node(self, old_id, new_id):
        self._conn.execute("UPDATE nodes SET id = ? WHERE id = ?", (new_id, old_id))
        self._conn.execute(
            "UPDATE history SET node_id = ? WHERE node_id = ?", (new_id, old_id)
        )
        self._conn.execute(
            "UPDATE labels SET node_id = ? WHERE node_id = ?", (new_id, old_id)
        )
        self._conn.execute(
            "UPDATE artifacts SET item_id = ? WHERE item_id = ?", (new_id, old_id)
        )
        self._conn.execute(
            "UPDATE deps SET node_id = ? WHERE node_id = ?", (new_id, old_id)
        )
        self._conn.execute(
            "UPDATE deps SET blocked_by = ? WHERE blocked_by = ?", (new_id, old_id)
        )

    def edit_node(self, tid, *, title=None, description=None, goal=None, project=None,
                  parent=None, workflow=None):
        updates = {}
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if goal is not None:
            updates["goal"] = goal
        if project is not None:
            updates["project"] = project
        if workflow is not None:
            updates["workflow"] = workflow

        effective_id = tid
        if parent is not None:
            row = self._conn.execute(
                "SELECT type, parent FROM nodes WHERE id = ?", (tid,)
            ).fetchone()
            if row is not None:
                cur_type, cur_parent = row
                if cur_type == "item" and parent != cur_parent and self._is_referenceless(tid):
                    effective_id = self._mint_id(parent)
                    self._rename_node(tid, effective_id)
            updates["parent"] = parent

        if updates:
            set_clause = ", ".join("%s = ?" % k for k in updates)
            self._conn.execute(
                "UPDATE nodes SET %s WHERE id = ?" % set_clause,
                (*updates.values(), effective_id),
            )
        self._conn.commit()
        return effective_id

    def create_item(self, title, *, theme=None, project=None, goal=None, workflow=None, id=None):
        tid = self._mint_or_adopt(id, theme)
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, state, parent, project, goal, workflow, "
            "created_at) VALUES (?, 'item', ?, 'backlogged', ?, ?, ?, ?, ?)",
            (tid, title, theme, project, goal, workflow, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def _shortcode_for(self, project):
        if not project:
            return self._config.shortcode()
        matches = self._match_projects(project)
        if len(matches) == 1 and matches[0].shortcode:
            return matches[0].shortcode
        return self._config.shortcode()

    def create_theme(self, title, *, project=None, goal=None, workflow=None, id=None):
        tid = self._mint_or_adopt(id, None, shortcode=self._shortcode_for(project))
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, state, project, goal, workflow, created_at) "
            "VALUES (?, 'theme', ?, 'backlogged', ?, ?, ?, ?)",
            (tid, title, project, goal, workflow, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def children(self, item_id):
        return self._select("parent = ?", (item_id,))

    def claimed_steps(self):
        return self._select("state = 'in_progress'")

    def history(self, tid):
        rows = self._conn.execute(
            "SELECT state, ts FROM history WHERE node_id = ? ORDER BY seq ASC", (tid,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def nodes_closed_since(self, since_date):
        return self._select(
            "type = 'step' AND state = 'done' AND substr(closed_at, 1, 10) >= ?",
            (since_date,),
        )

    def last_n_closed_themes(self, n):
        return self._select(
            "type = 'theme' AND state = 'done'",
            params=(n,),
            suffix="ORDER BY closed_at DESC LIMIT ?",
        )


    def closed_unretroed_items(self):
        return self._select(
            "type = 'item' AND state = 'done' "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = 'retro-origin') "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = 'retroed')",
        )

    def last_n_closed_items(self, n):
        return self._select(
            "type = 'item' AND state = 'done'",
            params=(n,),
            suffix="ORDER BY closed_at DESC LIMIT ?",
        )

    def steps_at_step(self, step):
        return self._select("type = 'step' AND step = ?", (step,))

    def delete(self, tid):
        self._conn.execute("DELETE FROM nodes WHERE id = ?", (tid,))
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

    def resolve_project_path(self, ref):
        if os.path.isabs(ref):
            return ref
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
        project = matches[0]
        if not project.local_path:
            raise ProjectResolutionError(
                "project '%s' is registered but has no local checkout - run "
                "`lc project add %s --path <dir>` to point at one (cloning on demand is not "
                "supported yet)" % (project.identity, project.identity)
            )
        return project.local_path
