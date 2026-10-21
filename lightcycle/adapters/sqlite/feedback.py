import datetime
from lightcycle.domain.feedback import APPROVED, DISPATCHED, HELD, HeldComment, can_transition
from lightcycle.domain.work import DailySummary
from lightcycle.ports.store import StoreError


class FeedbackAggregate:
    _HOLD_COLUMNS = (
        "run_id, key, author, body, path, line, created_at, state, item_id, step_id, decided_at"
    )

    def file_hold(self, run_id, key, author, body, path, line, created_at):
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO held_comments "
            "(run_id, key, author, body, path, line, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, key, author, body, path, line, created_at),
        )
        self._commit()
        return cur.rowcount == 1

    def attach_hold(self, run_id, key, item_id, step_id):
        self._conn.execute(
            "UPDATE held_comments SET item_id = ?, step_id = ? WHERE run_id = ? AND key = ?",
            (item_id, step_id, run_id, key),
        )
        self._commit()

    def hold(self, run_id, key):
        row = self._conn.execute(
            "SELECT %s FROM held_comments WHERE run_id = ? AND key = ?" % self._HOLD_COLUMNS,
            (run_id, key),
        ).fetchone()
        return HeldComment(*row) if row else None

    def hold_for_step(self, step_id):
        row = self._conn.execute(
            "SELECT %s FROM held_comments WHERE step_id = ?" % self._HOLD_COLUMNS, (step_id,)
        ).fetchone()
        return HeldComment(*row) if row else None

    def _holds_in_state(self, run_id, state):
        rows = self._conn.execute(
            "SELECT %s FROM held_comments WHERE run_id = ? AND state = ? "
            "ORDER BY created_at, key" % self._HOLD_COLUMNS,
            (run_id, state),
        ).fetchall()
        return [HeldComment(*r) for r in rows]

    def approved_holds(self, run_id):
        return self._holds_in_state(run_id, APPROVED)

    def open_holds(self, run_id):
        return self._holds_in_state(run_id, HELD)

    def _transition_hold(self, where, params, target):
        row = self._conn.execute(
            "SELECT state FROM held_comments WHERE %s" % where, params
        ).fetchone()
        if row is None:
            raise StoreError("no held comment for %s" % (params,))
        if not can_transition(row[0], target):
            raise StoreError("held comment is %s; cannot become %s" % (row[0], target))
        self._conn.execute(
            "UPDATE held_comments SET state = ?, decided_at = ? WHERE %s" % where,
            (target, self._now()) + tuple(params),
        )
        self._commit()

    def decide_hold(self, step_id, state):
        self._transition_hold("step_id = ?", (step_id,), state)

    def mark_hold_dispatched(self, run_id, key):
        self._transition_hold("run_id = ? AND key = ?", (run_id, key), DISPATCHED)

    def set_comments_handled_through(self, rid, value):
        self._conn.execute(
            "UPDATE phase_runs SET comments_handled_through = ? WHERE id = ?", (value, rid)
        )
        self._commit()

    def feedback_cutoff(self, pr):
        row = self._conn.execute(
            "SELECT cutoff, cutoff_head FROM pr_feedback_cutoffs WHERE pr = ?", (pr,)
        ).fetchone()
        return (row[0], row[1]) if row else None

    def save_feedback_cutoff(self, pr, cutoff, cutoff_head):
        self._conn.execute(
            "INSERT OR REPLACE INTO pr_feedback_cutoffs (pr, cutoff, cutoff_head, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (pr, cutoff, cutoff_head, self._now()),
        )
        self._commit()

    def pool_updated_heads(self, pr):
        rows = self._conn.execute(
            "SELECT head_sha FROM pr_pool_updates WHERE pr = ? ORDER BY head_sha", (pr,)
        ).fetchall()
        return [r[0] for r in rows]

    def record_pool_update(self, pr, head_sha):
        self._conn.execute(
            "INSERT OR IGNORE INTO pr_pool_updates (pr, head_sha, updated_at) VALUES (?, ?, ?)",
            (pr, head_sha, self._now()),
        )
        self._commit()

    def prune_pr_feedback_state(self, max_age_days):
        threshold = (
            datetime.datetime.fromisoformat(self._now()) - datetime.timedelta(days=max_age_days)
        ).isoformat()
        for table in ("pr_feedback_cutoffs", "pr_pool_updates"):
            self._conn.execute("DELETE FROM %s WHERE updated_at < ?" % table, (threshold,))
        self._commit()

    def day_summary(self, day):
        row = self._conn.execute(
            "SELECT day, summary, generated_at, summarized_count, dirty_since, step_id, "
            "spawn_count FROM daily_summaries WHERE day = ?",
            (day.isoformat(),),
        ).fetchone()
        if row is None:
            return None
        return DailySummary(
            day=datetime.date.fromisoformat(row[0]), summary=row[1], generated_at=row[2],
            summarized_count=row[3], dirty_since=row[4], step_id=row[5], spawn_count=row[6],
        )

    def mark_day_summary_dirty(self, day):
        self._conn.execute(
            "INSERT INTO daily_summaries (day, dirty_since) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET dirty_since = excluded.dirty_since "
            "WHERE daily_summaries.dirty_since IS NULL",
            (day.isoformat(), self._now()),
        )
        self._commit()

    def start_day_summary(self, day, step_id, spawn_count):
        self._conn.execute(
            "UPDATE daily_summaries SET step_id = ?, spawn_count = ? WHERE day = ?",
            (step_id, spawn_count, day.isoformat()),
        )
        self._commit()

    def finish_day_summary(self, day, summary, summarized_count, clear_dirty):
        if clear_dirty:
            self._conn.execute(
                "UPDATE daily_summaries SET summary = ?, generated_at = ?, summarized_count = ?, "
                "step_id = NULL, spawn_count = NULL, dirty_since = NULL WHERE day = ?",
                (summary, self._now(), summarized_count, day.isoformat()),
            )
        else:
            self._conn.execute(
                "UPDATE daily_summaries SET summary = ?, generated_at = ?, summarized_count = ?, "
                "step_id = NULL, spawn_count = NULL WHERE day = ?",
                (summary, self._now(), summarized_count, day.isoformat()),
            )
        self._commit()

    def release_day_summary(self, day):
        self._conn.execute(
            "UPDATE daily_summaries SET step_id = NULL, spawn_count = NULL WHERE day = ?",
            (day.isoformat(),),
        )
        self._commit()

    def summary_day_for_step(self, step_id):
        row = self._conn.execute(
            "SELECT day FROM daily_summaries WHERE step_id = ?", (step_id,)
        ).fetchone()
        return datetime.date.fromisoformat(row[0]) if row else None

    def request_schedule_run(self, schedule_id):
        self._conn.execute(
            "INSERT OR IGNORE INTO schedule_run_requests (schedule_id, requested_at) VALUES (?, ?)",
            (schedule_id, self._now()),
        )
        self._commit()

    def schedule_run_requested(self, schedule_id):
        row = self._conn.execute(
            "SELECT 1 FROM schedule_run_requests WHERE schedule_id = ?", (schedule_id,)
        ).fetchone()
        return row is not None

    def clear_schedule_run_request(self, schedule_id):
        self._conn.execute(
            "DELETE FROM schedule_run_requests WHERE schedule_id = ?", (schedule_id,)
        )
        self._commit()
