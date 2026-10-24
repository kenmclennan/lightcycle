from lightcycle.domain.feedback import ReviewEscape
from lightcycle.domain.runs import Pass, PhaseRun, RunState, run_id
from lightcycle.adapters.sqlite.shared import _RUN_SELECT


class RunsAggregate:
    def open_pass(self, item):
        row = self._conn.execute(
            "INSERT INTO passes (id, item, n, state, opened_at) "
            "SELECT ? || '.p' || (COALESCE(MAX(n), 0) + 1), ?, COALESCE(MAX(n), 0) + 1, "
            "'open', ? FROM passes WHERE item = ? "
            "RETURNING id",
            (item, item, self._now(), item),
        ).fetchone()
        self._commit()
        return row[0]

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
        self._commit()

    def open_run(self, item, pid, phase):
        open_sql = (
            "SELECT id FROM phase_runs WHERE item = ? AND pass_id = ? AND phase IS ? "
            "AND state = 'open' ORDER BY opened_at DESC, rowid DESC LIMIT 1"
        )
        found = self._conn.execute(open_sql, (item, pid, phase)).fetchone()
        if found:
            return found[0]
        (existing,) = self._conn.execute(
            "SELECT COUNT(*) FROM phase_runs WHERE item = ? AND pass_id = ? AND phase IS ?",
            (item, pid, phase),
        ).fetchone()
        self._conn.execute(
            "INSERT OR IGNORE INTO phase_runs (id, item, pass_id, phase, state, opened_at) "
            "VALUES (?, ?, ?, ?, 'open', ?)",
            (run_id(pid, phase, existing + 1), item, pid, phase, self._now()),
        )
        self._commit()
        return self._conn.execute(open_sql, (item, pid, phase)).fetchone()[0]

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
            "ORDER BY opened_at DESC, rowid DESC LIMIT 1" % _RUN_SELECT,
            (item, phase),
        ).fetchone()
        return self._run_row_to_record(row) if row else None

    def runs_of(self, item, pid=None):
        if pid is None:
            rows = self._conn.execute(
                "%s WHERE item = ? ORDER BY opened_at, rowid" % _RUN_SELECT, (item,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "%s WHERE item = ? AND pass_id = ? ORDER BY opened_at, rowid" % _RUN_SELECT, (item, pid)
            ).fetchall()
        return [self._run_row_to_record(r) for r in rows]

    def open_runs_of(self, item, pid=None):
        return [r for r in self.runs_of(item, pid) if r.is_open]

    def set_branch(self, rid, branch):
        self._conn.execute(
            "UPDATE phase_runs SET branch = ? WHERE id = ?", (branch, rid)
        )
        self._commit()

    def set_pr(self, rid, pr):
        self._conn.execute("UPDATE phase_runs SET pr = ? WHERE id = ?", (pr, rid))
        self._commit()

    def set_content_pin(self, rid, content_pin):
        self._conn.execute(
            "UPDATE phase_runs SET content_pin = ? WHERE id = ?", (content_pin, rid)
        )
        self._commit()

    def record_pr_pin(self, rid, pr, content_pin):
        self._conn.execute(
            "UPDATE phase_runs SET pr = ?, content_pin = ? WHERE id = ?", (pr, content_pin, rid)
        )
        self._commit()

    def set_comments_dispatched_through(self, rid, value):
        self._conn.execute(
            "UPDATE phase_runs SET comments_dispatched_through = ? WHERE id = ?", (value, rid)
        )
        self._commit()

    def close_run(self, rid, state=RunState.MERGED):
        self._conn.execute(
            "UPDATE phase_runs SET state = ?, closed_at = ? WHERE id = ? AND state = 'open'",
            (state, self._now(), rid),
        )
        self._commit()

    def set_watched_step(self, tid, watched):
        self._conn.execute("UPDATE steps SET watched_step = ? WHERE id = ?", (watched, tid))
        self._commit()

    def set_step_pass(self, tid, pid):
        self._conn.execute("UPDATE steps SET pass_id = ? WHERE id = ?", (pid, tid))
        self._commit()

    _ESCAPE_COLUMNS = (
        "trigger_step, item, run_id, verdict_step, via, at, note, source, authors"
    )

    def record_escape(self, escape):
        self._conn.execute(
            "INSERT OR IGNORE INTO review_escapes (%s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            % self._ESCAPE_COLUMNS,
            (escape.trigger_step, escape.item, escape.run_id, escape.verdict_step, escape.via,
             escape.at, escape.note, escape.source, escape.authors),
        )
        self._commit()

    def escapes_since(self, since_date):
        rows = self._conn.execute(
            "SELECT %s FROM review_escapes WHERE substr(at, 1, 10) >= ? ORDER BY at, trigger_step"
            % self._ESCAPE_COLUMNS,
            (since_date,),
        ).fetchall()
        return [ReviewEscape(*r) for r in rows]
