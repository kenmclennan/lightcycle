import datetime
import os
import sqlite3

from the_grid.domain.work import Artifact, Status, Task, TaskView
from the_grid.ports.store import StorePort

_DB_FILENAME = ".grid.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
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
    epic TEXT,
    needs TEXT,
    model TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent);

CREATE TABLE IF NOT EXISTS deps (
    task_id TEXT NOT NULL,
    blocked_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deps_task_id ON deps(task_id);

CREATE TABLE IF NOT EXISTS artifacts (
    story_id TEXT NOT NULL,
    atype TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT
);

CREATE TABLE IF NOT EXISTS labels (
    task_id TEXT NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    namespace TEXT PRIMARY KEY,
    next INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    task_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL
);
"""

_COLUMNS = (
    "id", "type", "title", "status", "step", "role", "parent", "project", "goal",
    "description", "notes", "close_reason", "assignee", "since", "fired_at",
    "closed_at", "attention", "epic", "needs", "model",
)

_METADATA_COLUMNS = ("epic", "needs", "since", "fired_at")

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
    def __init__(self, config):
        self._config = config
        path = os.path.join(config.grid_root(), _DB_FILENAME)
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _row_to_task(self, row, artifacts, deps):
        d = dict(zip(_COLUMNS, row))
        return Task(
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
            epic=d["epic"],
            since=d["since"],
            fired_at=d["fired_at"],
            closed_at=d["closed_at"],
            attention=bool(d["attention"]),
            model=d["model"],
        )

    def _rows_to_tasks(self, rows):
        if not rows:
            return []
        ids = [r[0] for r in rows]
        placeholders = ", ".join("?" * len(ids))

        artifacts_by_id = {}
        for story_id, atype, value, label in self._conn.execute(
            "SELECT story_id, atype, value, label FROM artifacts "
            "WHERE story_id IN (%s) ORDER BY rowid" % placeholders,
            ids,
        ).fetchall():
            artifacts_by_id.setdefault(story_id, []).append(
                Artifact(type=atype, value=value, label=label)
            )

        deps_by_id = dict(
            self._conn.execute(
                "SELECT d.task_id, COUNT(*) FROM deps d JOIN tasks t ON t.id = d.blocked_by "
                "WHERE t.status != 'closed' AND d.task_id IN (%s) GROUP BY d.task_id"
                % placeholders,
                ids,
            ).fetchall()
        )

        return [
            self._row_to_task(row, artifacts_by_id.get(row[0], []), deps_by_id.get(row[0], 0))
            for row in rows
        ]

    def _select(self, where, params=(), suffix=""):
        sql = "SELECT %s FROM tasks" % ", ".join(_COLUMNS)
        if where:
            sql += " WHERE " + where
        if suffix:
            sql += " " + suffix
        rows = self._conn.execute(sql, params).fetchall()
        return self._rows_to_tasks(rows)

    def _mint_id(self, parent):
        namespace = parent if parent is not None else self.shortcode()
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
            return "%s-%d" % (self.shortcode(), n)
        return "%s.%d" % (parent, n)

    def _mint_or_adopt(self, explicit_id, parent):
        if explicit_id is None:
            return self._mint_id(parent)
        exists = self._conn.execute(
            "SELECT 1 FROM tasks WHERE id = ?", (explicit_id,)
        ).fetchone()
        if exists:
            raise ValueError("id already in use: %s" % explicit_id)
        return explicit_id

    def _apply_label(self, tid, label, value):
        if label == "attention":
            self._conn.execute(
                "UPDATE tasks SET attention = ? WHERE id = ?", (1 if value else 0, tid)
            )
            return True
        prefix, sep, val = label.partition(":")
        column = _LABEL_COLUMNS.get(prefix) if sep else None
        if column:
            self._conn.execute(
                "UPDATE tasks SET %s = ? WHERE id = ?" % column, (val if value else None, tid)
            )
            return True
        return False

    def _record_history(self, tid, status):
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) FROM history WHERE task_id = ?", (tid,)
        ).fetchone()
        self._conn.execute(
            "INSERT INTO history (task_id, seq, status) VALUES (?, ?, ?)",
            (tid, row[0] + 1, status),
        )

    def story_artifacts(self, story_id):
        rows = self._conn.execute(
            "SELECT atype, value, label FROM artifacts WHERE story_id = ? ORDER BY rowid",
            (story_id,),
        ).fetchall()
        return [Artifact(type=r[0], value=r[1], label=r[2]) for r in rows]

    def add_artifact(self, story_id, atype, value, label=None):
        self._conn.execute(
            "INSERT INTO artifacts (story_id, atype, value, label) VALUES (?, ?, ?, ?)",
            (story_id, atype, value, label),
        )
        self._conn.commit()

    def all_tasks(self):
        return self._select("status != 'closed'")

    def get_task(self, tid):
        row = self._conn.execute(
            "SELECT %s FROM tasks WHERE id = ?" % ", ".join(_COLUMNS), (tid,)
        ).fetchone()
        if row is None:
            raise KeyError("task not found: %s" % tid)
        return self._rows_to_tasks([row])[0]

    def task_view(self, tid):
        t = self.get_task(tid)
        arts = self.story_artifacts(t.parent) if t.parent else t.artifacts
        return TaskView(task=t, story_artifacts=list(arts))

    def present_types(self, task):
        story = task.parent or task.id
        return {a.type for a in self.story_artifacts(story)}

    def reassign(self, tid, role):
        cur = self.get_task(tid).role
        if cur and cur != role:
            self.label_remove(tid, "for:%s" % cur)
        self.label_add(tid, "for:%s" % role)
        self.update_status(tid, "open")
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_stories(self):
        rows = self._conn.execute(
            "SELECT id, title, closed_at, close_reason FROM tasks "
            "WHERE type = 'story' AND status = 'closed'"
        ).fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "closed_at": r[2],
                "outcome": r[3],
                "artifacts": self.story_artifacts(r[0]),
            }
            for r in rows
        ]

    def shortcode(self):
        return self._config.shortcode()

    def export_rows(self):
        export_columns = _COLUMNS + ("created_at",)
        rows = self._conn.execute(
            "SELECT %s FROM tasks ORDER BY rowid" % ", ".join(export_columns)
        ).fetchall()
        result = []
        for row in rows:
            d = dict(zip(export_columns, row))
            tid = d["id"]
            artifacts = self.story_artifacts(tid)
            blocked_by = [
                r[0] for r in self._conn.execute(
                    "SELECT blocked_by FROM deps WHERE task_id = ?", (tid,)
                ).fetchall()
            ]
            labels = [
                r[0] for r in self._conn.execute(
                    "SELECT label FROM labels WHERE task_id = ?", (tid,)
                ).fetchall()
            ]
            result.append({
                "id": tid, "type": d["type"], "title": d["title"], "status": d["status"],
                "parent": d["parent"], "role": d["role"], "step": d["step"],
                "project": d["project"], "goal": d["goal"], "attention": bool(d["attention"]),
                "description": d["description"], "notes": d["notes"],
                "close_reason": d["close_reason"], "assignee": d["assignee"], "epic": d["epic"],
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
        row = self._conn.execute("SELECT notes FROM tasks WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise KeyError("task not found: %s" % tid)
        combined = (row[0] + "\n" + text) if row[0] else text
        self._conn.execute("UPDATE tasks SET notes = ? WHERE id = ?", (combined, tid))
        self._conn.commit()

    def set_notes(self, tid, text):
        row = self._conn.execute("SELECT 1 FROM tasks WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise KeyError("task not found: %s" % tid)
        self._conn.execute("UPDATE tasks SET notes = ? WHERE id = ?", (text or None, tid))
        self._conn.commit()

    def close(self, tid, reason):
        self._conn.execute(
            "UPDATE tasks SET status = 'closed', close_reason = ?, closed_at = ? WHERE id = ?",
            (reason, datetime.datetime.now().isoformat(), tid),
        )
        self._conn.commit()

    def update_metadata(self, tid, meta):
        updates = {k: v for k, v in meta.items() if k in _METADATA_COLUMNS}
        if not updates:
            return
        set_clause = ", ".join("%s = ?" % k for k in updates)
        self._conn.execute(
            "UPDATE tasks SET %s WHERE id = ?" % set_clause, (*updates.values(), tid)
        )
        self._conn.commit()

    def set_model(self, tid, model):
        self._conn.execute("UPDATE tasks SET model = ? WHERE id = ?", (model, tid))
        self._conn.commit()

    def label_add(self, tid, label):
        if not self._apply_label(tid, label, True):
            exists = self._conn.execute(
                "SELECT 1 FROM labels WHERE task_id = ? AND label = ?", (tid, label)
            ).fetchone()
            if not exists:
                self._conn.execute(
                    "INSERT INTO labels (task_id, label) VALUES (?, ?)", (tid, label)
                )
        self._conn.commit()

    def label_remove(self, tid, label):
        if not self._apply_label(tid, label, False):
            self._conn.execute(
                "DELETE FROM labels WHERE task_id = ? AND label = ?", (tid, label)
            )
        self._conn.commit()

    def update_status(self, tid, status):
        self._conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, tid))
        self._record_history(tid, status)
        self._conn.commit()

    def assign(self, tid, assignee):
        self._conn.execute(
            "UPDATE tasks SET assignee = ? WHERE id = ?", (assignee or None, tid)
        )
        self._conn.commit()

    def dep_add(self, task_id, blocked_by):
        exists = self._conn.execute(
            "SELECT 1 FROM deps WHERE task_id = ? AND blocked_by = ?", (task_id, blocked_by)
        ).fetchone()
        if not exists:
            self._conn.execute(
                "INSERT INTO deps (task_id, blocked_by) VALUES (?, ?)", (task_id, blocked_by)
            )
            self._conn.commit()

    def ready_tasks(self):
        return self._select(
            "type = 'task' AND status = 'open' AND assignee IS NULL AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN tasks b ON b.id = d.blocked_by "
            "  WHERE d.task_id = tasks.id AND b.status != 'closed'"
            ")"
        )

    def claim_ready(self, role):
        row = self._conn.execute(
            "SELECT id FROM tasks WHERE type = 'task' AND status = 'open' "
            "AND assignee IS NULL AND role = ? AND NOT EXISTS ("
            "  SELECT 1 FROM deps d JOIN tasks b ON b.id = d.blocked_by "
            "  WHERE d.task_id = tasks.id AND b.status != 'closed'"
            ") LIMIT 1",
            (role,),
        ).fetchone()
        if row is None:
            return None
        tid = row[0]
        assignee = self._config.spawn_id() or role
        self._conn.execute(
            "UPDATE tasks SET assignee = ?, status = 'in_progress' WHERE id = ?", (assignee, tid)
        )
        self._conn.commit()
        return self.get_task(tid)

    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False, id=None):
        tid = self._mint_or_adopt(id, parent)
        self._conn.execute(
            "INSERT INTO tasks (id, type, title, status, step, role, parent, project, goal, "
            "description, attention, created_at) VALUES (?, 'task', ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, title, step, role, parent, project, goal, description,
             1 if attention else 0, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        if deps:
            for dep in deps:
                self.dep_add(tid, dep)
        return tid

    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
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
        if not updates:
            return
        set_clause = ", ".join("%s = ?" % k for k in updates)
        self._conn.execute(
            "UPDATE tasks SET %s WHERE id = ?" % set_clause, (*updates.values(), tid)
        )
        self._conn.commit()

    def create_story(self, title, *, epic=None, project=None, goal=None, id=None):
        if not epic:
            raise ValueError("story requires an epic parent")
        tid = self._mint_or_adopt(id, epic)
        self._conn.execute(
            "INSERT INTO tasks (id, type, title, status, parent, project, goal, created_at) "
            "VALUES (?, 'story', ?, 'open', ?, ?, ?, ?)",
            (tid, title, epic, project, goal, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def create_epic(self, title, *, project=None, goal=None, id=None):
        tid = self._mint_or_adopt(id, None)
        self._conn.execute(
            "INSERT INTO tasks (id, type, title, status, project, goal, created_at) "
            "VALUES (?, 'epic', ?, 'open', ?, ?, ?)",
            (tid, title, project, goal, datetime.datetime.now().isoformat()),
        )
        self._conn.commit()
        return tid

    def children(self, story_id):
        return self._select("parent = ?", (story_id,))

    def claimed_tasks(self):
        return self._select("status = 'in_progress'")

    def history(self, tid):
        rows = self._conn.execute(
            "SELECT status FROM history WHERE task_id = ? ORDER BY seq DESC", (tid,)
        ).fetchall()
        return [{"Issue": {"status": r[0]}} for r in rows]

    def tasks_closed_since(self, since_date):
        return self._select(
            "type = 'task' AND status = 'closed' AND substr(closed_at, 1, 10) >= ?",
            (since_date,),
        )

    def last_n_closed_epics(self, n):
        return self._select(
            "type = 'epic' AND status = 'closed'",
            params=(n,),
            suffix="ORDER BY closed_at DESC LIMIT ?",
        )

    def epics_closed_since(self, since_date_str):
        return self._select(
            "type = 'epic' AND status = 'closed' "
            "AND substr(closed_at, 1, 10) >= ? "
            "AND id NOT IN (SELECT task_id FROM labels WHERE label = 'retro-origin')",
            (since_date_str,),
        )

    def tasks_at_step(self, step):
        return self._select("type = 'task' AND step = ?", (step,))

    def delete(self, tid):
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        self._conn.execute("DELETE FROM deps WHERE task_id = ? OR blocked_by = ?", (tid, tid))
        self._conn.execute("DELETE FROM artifacts WHERE story_id = ?", (tid,))
        self._conn.execute("DELETE FROM labels WHERE task_id = ?", (tid,))
        self._conn.execute("DELETE FROM history WHERE task_id = ?", (tid,))
        self._conn.commit()
