from lightcycle.domain.goals import GOAL_DEFAULT_STATUS, Goal, GoalLogEntry


class GoalsAggregate:
    def create_goal(self, title, description="", project=""):
        row = self._conn.execute(
            "INSERT INTO counters (namespace, next) VALUES ('goal', 2) "
            "ON CONFLICT(namespace) DO UPDATE SET next = next + 1 "
            "RETURNING next - 1"
        ).fetchone()
        gid = "G-%d" % row[0]
        now = self._now()
        self._conn.execute(
            "INSERT INTO goals (id, title, description, project, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gid, title, description, project, GOAL_DEFAULT_STATUS, now, now),
        )
        self._commit()
        return gid

    def get_goal(self, goal_id):
        row = self._conn.execute(
            "SELECT id, title, description, project, status, created_at, updated_at "
            "FROM goals WHERE id = ?",
            (goal_id,),
        ).fetchone()
        return Goal(*row) if row else None

    def list_goals(self):
        rows = self._conn.execute(
            "SELECT id, title, description, project, status, created_at, updated_at "
            "FROM goals"
        ).fetchall()
        goals = [Goal(*r) for r in rows]
        goals.sort(key=lambda g: int(g.id.split("-", 1)[1]))
        return goals

    def update_goal(self, goal_id, *, title=None, description=None, project=None, status=None):
        fields = {
            "title": title, "description": description, "project": project, "status": status,
        }
        sets = [(k, v) for k, v in fields.items() if v is not None]
        if not sets:
            return
        assignments = ", ".join("%s = ?" % k for k, _ in sets)
        self._conn.execute(
            "UPDATE goals SET %s, updated_at = ? WHERE id = ?" % assignments,
            [v for _, v in sets] + [self._now(), goal_id],
        )
        self._commit()

    def add_goal_log(self, goal_id, title, body):
        self._conn.execute(
            "INSERT INTO goal_log (goal_id, title, body, created_at) VALUES (?, ?, ?, ?)",
            (goal_id, title, body, self._now()),
        )
        self._commit()

    def goal_log(self, goal_id):
        rows = self._conn.execute(
            "SELECT id, goal_id, title, body, created_at FROM goal_log "
            "WHERE goal_id = ? ORDER BY id DESC",
            (goal_id,),
        ).fetchall()
        return [GoalLogEntry(*r) for r in rows]

    def link_goal_item(self, goal_id, item_id):
        self._conn.execute(
            "INSERT OR IGNORE INTO goal_items (goal_id, item_id, linked_at) VALUES (?, ?, ?)",
            (goal_id, item_id, self._now()),
        )
        self._commit()

    def unlink_goal_item(self, goal_id, item_id):
        self._conn.execute(
            "DELETE FROM goal_items WHERE goal_id = ? AND item_id = ?", (goal_id, item_id)
        )
        self._commit()

    def goal_items(self, goal_id):
        rows = self._conn.execute(
            "SELECT item_id FROM goal_items WHERE goal_id = ? ORDER BY rowid", (goal_id,)
        ).fetchall()
        return [r[0] for r in rows]
