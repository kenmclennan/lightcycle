import sqlite3

_LEGACY_NODES = """
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
    needs TEXT,
    model TEXT,
    workflow TEXT,
    branch TEXT,
    pr TEXT,
    reason TEXT,
    tried TEXT,
    pass_id TEXT
);
"""

_COLUMNS = (
    "id", "type", "title", "state", "step", "role", "parent", "project", "goal",
    "description", "notes", "outcome", "assignee", "since", "fired_at", "closed_at",
    "created_at", "attention", "needs", "model", "workflow", "branch", "pr",
    "reason", "tried", "pass_id",
)


def plant_legacy_nodes(db_path, rows, artifacts=()):
    conn = sqlite3.connect(db_path)
    conn.executescript(_LEGACY_NODES)
    for row in rows:
        values = [row.get(c) for c in _COLUMNS]
        conn.execute(
            "INSERT OR REPLACE INTO nodes (%s) VALUES (%s)"
            % (", ".join(_COLUMNS), ", ".join("?" * len(_COLUMNS))),
            values,
        )
    for a in artifacts:
        conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label, internal, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (a["item_id"], a["atype"], a["value"], a.get("label"),
             1 if a.get("internal") else 0, a.get("kind", "text")),
        )
    conn.commit()
    conn.close()
