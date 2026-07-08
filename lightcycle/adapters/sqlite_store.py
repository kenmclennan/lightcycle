import datetime
import os
import sqlite3

from lightcycle.domain.work import Artifact, Status, Node, NodeView
from lightcycle.ports.store import StorePort

_DB_FILENAME = "store.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
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

CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
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
    status TEXT NOT NULL,
    ts TEXT
);
"""

_COLUMNS = (
    "id", "type", "title", "status", "step", "role", "parent", "project", "goal",
    "description", "notes", "close_reason", "assignee", "since", "fired_at",
    "closed_at", "attention", "theme", "needs", "model", "workflow", "state",
)

_METADATA_COLUMNS = ("theme", "needs", "since", "fired_at", "workflow")

_LABEL_COLUMNS = {"for": "role", "step": "step", "project": "project", "goal": "goal"}


def _domain_status(raw_status, assignee, role):
    if raw_status == "closed":
        return Status.DONE
    if assignee:
        return Status.IN_PROGRESS
    if role == "human":
        return Status.NEEDS_HUMAN
    return Status.READY


class SqliteStore(StorePort):
    def __init__(self, config, now=None):
        self._config = config
        self._now = now or (lambda: datetime.datetime.now().isoformat())
        path = os.path.join(config.data_root(), _DB_FILENAME)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._migrate_history_ts()
        self._migrate_nodes_workflow()
        self._conn.commit()

    def _migrate_history_ts(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(history)").fetchall()}
        if "ts" not in cols:
            self._conn.execute("ALTER TABLE history ADD COLUMN ts TEXT")

    def _migrate_nodes_workflow(self):
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(nodes)").fetchall()}
        if "workflow" not in cols:
            self._conn.execute("ALTER TABLE nodes ADD COLUMN workflow TEXT")

    def _row_to_node(self, row, artifacts, deps):
        d = dict(zip(_COLUMNS, row))
        return Node(
            id=d["id"],
            title=d["title"],
            type=d["type"],
            parent=d["parent"],
            role=d["role"],
            step=d["step"],
            status=_domain_status(d["status"], d["assignee"], d["role"]),
            project=d["project"],
            goal=d["goal"],
            artifacts=artifacts,
            description=d["description"],
            needs=d["needs"],
            outcome=d["close_reason"],
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
            state=d["state"],
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
                "WHERE t.status != 'closed' AND d.node_id IN (%s) GROUP BY d.node_id"
                % placeholders,
                ids,
            ).fetchall()
        )

        return [
            self._row_to_node(row, artifacts_by_id.get(row[0], []), deps_by_id.get(row[0], 0))
            for row in rows
        ]

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

    def _record_history(self, tid, status):
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) FROM history WHERE node_id = ?", (tid,)
        ).fetchone()
        self._conn.execute(
            "INSERT INTO history (node_id, seq, status, ts) VALUES (?, ?, ?, ?)",
            (tid, row[0] + 1, str(status), self._now()),
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

    def all_nodes(self):
        return self._select("status != 'closed'")

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
        self.update_status(tid, "open")
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_items(self):
        rows = self._conn.execute(
            "SELECT id, title, closed_at, close_reason FROM nodes "
            "WHERE type = 'item' AND status = 'closed'"
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
                "id": tid, "type": d["type"], "title": d["title"], "status": d["status"],
                "parent": d["parent"], "role": d["role"], "step": d["step"],
                "project": d["project"], "goal": d["goal"], "attention": bool(d["attention"]),
                "description": d["description"], "notes": d["notes"],
                "close_reason": d["close_reason"], "assignee": d["assignee"], "theme": d["theme"],
                "needs": d["needs"], "artifacts": [a.as_dict() for a in artifacts],
                "blocked_by": blocked_by, "labels": labels, "since": d["since"],
                "fired_at": d["fired_at"], "closed_at": d["closed_at"],
                "created_at": d["created_at"],
            })
        return result

    def ensure_store(self):
        pass

    def reclaim(self, tid):
        self.update_status(tid, "open")
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
            "UPDATE nodes SET status = 'closed', close_reason = ?, closed_at = ? WHERE id = ?",
            (reason, datetime.datetime.now().isoformat(), tid),
        )
        self._record_history(tid, Status.DONE)
        self._conn.commit()

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

    def update_status(self, tid, status):
        self._conn.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, tid))
        self._record_history(tid, status)
        self._conn.commit()

    def assign(self, tid, assignee):
        self._conn.execute(
            "UPDATE nodes SET assignee = ? WHERE id = ?", (assignee or None, tid)
        )
        self._conn.commit()

    def dep_add(self, node_id, blocked_by):
        exists = self._conn.execute(
            "SELECT 1 FROM deps WHERE node_id = ? AND blocked_by = ?", (node_id, blocked_by)
        ).fetchone()
        if not exists:
            self._conn.execute(
                "INSERT INTO deps (node_id, blocked_by) VALUES (?, ?)", (node_id, blocked_by)
            )
            self._conn.commit()

    def ready_steps(self):
        return self._select(
            "type = 'step' AND status = 'open' AND assignee IS NULL AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN nodes b ON b.id = d.blocked_by "
            "  WHERE d.node_id = nodes.id AND b.status != 'closed'"
            ")"
        )

    def claim_ready(self, role):
        row = self._conn.execute(
            "SELECT id FROM nodes WHERE type = 'step' AND status = 'open' "
            "AND assignee IS NULL AND role = ? AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN nodes b ON b.id = d.blocked_by "
            "  WHERE d.node_id = nodes.id AND b.status != 'closed'"
            ") LIMIT 1",
            (role,),
        ).fetchone()
        if row is None:
            return None
        tid = row[0]
        assignee = self._config.spawn_id() or role
        self._conn.execute(
            "UPDATE nodes SET assignee = ?, status = 'in_progress' WHERE id = ?", (assignee, tid)
        )
        self._record_history(tid, Status.IN_PROGRESS)
        self._conn.commit()
        return self.get_node(tid)

    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False, id=None):
        tid = self._mint_or_adopt(id, parent)
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, status, step, role, parent, project, goal, "
            "description, attention, created_at) VALUES (?, 'step', ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, title, step, role, parent, project, goal, description,
             1 if attention else 0, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        if deps:
            for dep in deps:
                self.dep_add(tid, dep)
        return tid

    def edit_node(self, tid, *, title=None, description=None, goal=None, project=None,
                  parent=None, workflow=None, state=None):
        updates = {}
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if goal is not None:
            updates["goal"] = goal
        if project is not None:
            updates["project"] = project
        if parent is not None:
            updates["parent"] = parent
        if workflow is not None:
            updates["workflow"] = workflow
        if state is not None:
            updates["state"] = state
        if not updates:
            return
        set_clause = ", ".join("%s = ?" % k for k in updates)
        self._conn.execute(
            "UPDATE nodes SET %s WHERE id = ?" % set_clause, (*updates.values(), tid)
        )
        self._conn.commit()

    def create_item(self, title, *, theme=None, project=None, goal=None, workflow=None, id=None):
        tid = self._mint_or_adopt(id, theme)
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, status, parent, project, goal, workflow, "
            "state, created_at) VALUES (?, 'item', ?, 'open', ?, ?, ?, ?, 'todo', ?)",
            (tid, title, theme, project, goal, workflow, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def create_theme(self, title, *, project=None, goal=None, workflow=None, id=None):
        tid = self._mint_or_adopt(id, None, shortcode=self._config.shortcode_for(project))
        self._conn.execute(
            "INSERT INTO nodes (id, type, title, status, project, goal, workflow, created_at) "
            "VALUES (?, 'theme', ?, 'open', ?, ?, ?, ?)",
            (tid, title, project, goal, workflow, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def children(self, item_id):
        return self._select("parent = ?", (item_id,))

    def claimed_steps(self):
        return self._select("status = 'in_progress'")

    def history(self, tid):
        rows = self._conn.execute(
            "SELECT status, ts FROM history WHERE node_id = ? ORDER BY seq ASC", (tid,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def nodes_closed_since(self, since_date):
        return self._select(
            "type = 'step' AND status = 'closed' AND substr(closed_at, 1, 10) >= ?",
            (since_date,),
        )

    def last_n_closed_themes(self, n):
        return self._select(
            "type = 'theme' AND status = 'closed'",
            params=(n,),
            suffix="ORDER BY closed_at DESC LIMIT ?",
        )


    def items_closed_since(self, since_date):
        return self._select(
            "type = 'item' AND status = 'closed' AND substr(closed_at, 1, 10) >= ? "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = 'retro-origin')",
            (since_date,),
        )

    def last_n_closed_items(self, n):
        return self._select(
            "type = 'item' AND status = 'closed'",
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
