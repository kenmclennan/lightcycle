import json
from dataclasses import asdict
from lightcycle.domain.money import Cost
from lightcycle.domain.pool import ToolUsage, UsageResume


class UsageAggregate:
    def record_gh_calls(self, spawnid, step, calls):
        self._conn.execute(
            "INSERT INTO step_gh_calls (spawnid, step, calls) VALUES (?, ?, ?) "
            "ON CONFLICT(spawnid) DO UPDATE SET step = excluded.step, calls = excluded.calls",
            (spawnid, step, calls),
        )
        self._conn.execute(
            "UPDATE steps SET usage_api_calls = "
            "(SELECT SUM(calls) FROM step_gh_calls WHERE step = ?) WHERE id = ?",
            (step, step),
        )
        self._commit()

    def accrue_active_seconds(self, step_ids, seconds):
        ids = list(step_ids)
        if not ids:
            return
        placeholders = ", ".join("?" * len(ids))
        self._conn.execute(
            "UPDATE steps SET active_seconds = COALESCE(active_seconds, 0) + ? "
            "WHERE id IN (%s)" % placeholders,
            (seconds, *ids),
        )
        self._commit()

    def _record_usage_nocommit(self, tid, input_tokens, output_tokens, cache_read_tokens,
                                cache_creation_tokens, cost_usd, cost_basis, thinking_tokens,
                                rates_used=None):
        rates_used_json = json.dumps(asdict(rates_used)) if rates_used is not None else None
        cursor = self._conn.execute(
            "UPDATE steps SET "
            "usage_input_tokens = usage_input_tokens + ?, "
            "usage_output_tokens = usage_output_tokens + ?, "
            "usage_cache_read_tokens = usage_cache_read_tokens + ?, "
            "usage_cache_creation_tokens = usage_cache_creation_tokens + ?, "
            "usage_cost_usd = usage_cost_usd + ?, "
            "usage_cost_basis = COALESCE(?, usage_cost_basis), "
            "usage_rates_used = COALESCE(?, usage_rates_used), "
            "usage_thinking_tokens = CASE WHEN ? IS NULL THEN usage_thinking_tokens "
            "ELSE COALESCE(usage_thinking_tokens, 0) + ? END "
            "WHERE id = ?",
            (input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
             cost_usd, cost_basis, rates_used_json, thinking_tokens, thinking_tokens, tid),
        )
        return cursor.rowcount

    def record_usage(self, tid, input_tokens, output_tokens, cache_read_tokens,
                      cache_creation_tokens, cost_usd, cost_basis, thinking_tokens,
                      rates_used=None):
        self._record_usage_nocommit(
            tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
            cost_usd, cost_basis, thinking_tokens, rates_used=rates_used,
        )
        self._commit()

    def _record_attribution_nocommit(self, tid, turn_count, tool_usage):
        self._conn.execute(
            "UPDATE steps SET turn_count = turn_count + ? WHERE id = ?", (turn_count, tid),
        )
        for tool, usage in tool_usage.items():
            self._conn.execute(
                "INSERT INTO step_tool_usage (step, tool, calls, bytes) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(step, tool) DO UPDATE SET "
                "calls = calls + excluded.calls, bytes = bytes + excluded.bytes",
                (tid, tool, usage.calls, usage.bytes),
            )

    def record_attribution(self, tid, turn_count, tool_usage):
        self._record_attribution_nocommit(tid, turn_count, tool_usage)
        self._commit()

    def tool_usage_for(self, step_id):
        rows = self._conn.execute(
            "SELECT tool, calls, bytes FROM step_tool_usage WHERE step = ?", (step_id,)
        ).fetchall()
        return {tool: ToolUsage(calls=calls, bytes=bytes_) for tool, calls, bytes_ in rows}

    def usage_backfilled_logs(self):
        rows = self._conn.execute("SELECT log_file FROM usage_backfill_log").fetchall()
        return {r[0] for r in rows}

    def record_backfilled_usage(self, log_file, step_id, usage, attribution):
        try:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO usage_backfill_log "
                "(log_file, step, ingested_at, had_result_line) VALUES (?, ?, ?, ?)",
                (log_file, step_id, self._now(), 1 if usage.has_result_line else 0),
            )
            if cursor.rowcount == 0:
                self._conn.rollback()
                return False
            stored = False
            if step_id is not None:
                rowcount = self._record_usage_nocommit(
                    step_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                    usage.cache_creation_tokens, usage.cost_usd.to_usd(), usage.cost_basis,
                    usage.thinking_tokens, rates_used=usage.rates_used,
                )
                stored = rowcount > 0
                if stored:
                    self._record_attribution_nocommit(
                        step_id, attribution.turn_count, attribution.tool_usage
                    )
            self._commit()
            return stored
        except Exception:
            self._conn.rollback()
            raise

    def record_live_usage(
        self, spawnid, resume,
        tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
        cost_usd, cost_basis, thinking_tokens, turn_count, tool_usage,
        rates_used=None,
    ):
        try:
            self._conn.execute(
                "INSERT INTO usage_accrual_state ("
                "spawnid, log_file, offset, message_ids, pending_tool_use, "
                "posted_turn_count, posted_tool_usage, posted_input_tokens, "
                "posted_output_tokens, posted_cache_read_tokens, "
                "posted_cache_creation_tokens, posted_cost_usd"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(spawnid) DO UPDATE SET "
                "log_file = excluded.log_file, offset = excluded.offset, "
                "message_ids = excluded.message_ids, "
                "pending_tool_use = excluded.pending_tool_use, "
                "posted_turn_count = excluded.posted_turn_count, "
                "posted_tool_usage = excluded.posted_tool_usage, "
                "posted_input_tokens = excluded.posted_input_tokens, "
                "posted_output_tokens = excluded.posted_output_tokens, "
                "posted_cache_read_tokens = excluded.posted_cache_read_tokens, "
                "posted_cache_creation_tokens = excluded.posted_cache_creation_tokens, "
                "posted_cost_usd = excluded.posted_cost_usd",
                (
                    spawnid, resume.log_file, resume.offset, json.dumps(resume.message_ids),
                    json.dumps(resume.pending_tool_use), resume.posted_turn_count,
                    json.dumps(resume.posted_tool_usage), resume.posted_input_tokens,
                    resume.posted_output_tokens, resume.posted_cache_read_tokens,
                    resume.posted_cache_creation_tokens, resume.posted_cost.to_usd(),
                ),
            )
            if input_tokens or output_tokens or cache_read_tokens or cache_creation_tokens:
                self._record_usage_nocommit(
                    tid, input_tokens, output_tokens, cache_read_tokens,
                    cache_creation_tokens, cost_usd, cost_basis, thinking_tokens,
                    rates_used=rates_used,
                )
            if turn_count or tool_usage:
                self._record_attribution_nocommit(tid, turn_count, tool_usage)
            self._commit()
        except Exception:
            self._conn.rollback()
            raise

    def usage_accrual_state(self, spawnid):
        row = self._conn.execute(
            "SELECT log_file, offset, message_ids, pending_tool_use, posted_turn_count, "
            "posted_tool_usage, posted_input_tokens, posted_output_tokens, "
            "posted_cache_read_tokens, posted_cache_creation_tokens, posted_cost_usd "
            "FROM usage_accrual_state WHERE spawnid = ?",
            (spawnid,),
        ).fetchone()
        if row is None:
            return None
        return UsageResume(
            log_file=row[0],
            offset=row[1],
            message_ids=json.loads(row[2]),
            pending_tool_use=json.loads(row[3]),
            posted_turn_count=row[4],
            posted_tool_usage=json.loads(row[5]),
            posted_input_tokens=row[6],
            posted_output_tokens=row[7],
            posted_cache_read_tokens=row[8],
            posted_cache_creation_tokens=row[9],
            posted_cost=Cost.from_usd(row[10]),
        )

    def clear_usage_accrual_state(self, spawnid):
        self._conn.execute("DELETE FROM usage_accrual_state WHERE spawnid = ?", (spawnid,))
        self._commit()

    def _seed_unclassified_backfill_row(self, log_file, step_id):
        self._conn.execute(
            "INSERT INTO usage_backfill_log (log_file, step, ingested_at, had_result_line) "
            "VALUES (?, ?, ?, NULL)",
            (log_file, step_id, self._now()),
        )
        self._commit()

    def unclassified_backfill_logs(self):
        rows = self._conn.execute(
            "SELECT log_file, step FROM usage_backfill_log WHERE had_result_line IS NULL"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def reclassify_backfilled_log(self, log_file, step_id, usage, attribution):
        recovered = False
        if not usage.has_result_line and step_id is not None:
            rowcount = self._record_usage_nocommit(
                step_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                usage.cache_creation_tokens, usage.cost_usd.to_usd(), usage.cost_basis,
                usage.thinking_tokens, rates_used=usage.rates_used,
            )
            recovered = rowcount > 0
        self._conn.execute(
            "UPDATE usage_backfill_log SET had_result_line = ? WHERE log_file = ?",
            (1 if usage.has_result_line else 0, log_file),
        )
        self._commit()
        return recovered

    def logs_for_step(self, step_id):
        rows = self._conn.execute(
            "SELECT log_file FROM usage_backfill_log WHERE step = ?", (step_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def overwrite_usage_and_attribution(self, step_id, usage_totals, turn_count, tool_usage_totals):
        rates_used_json = (
            json.dumps(asdict(usage_totals.rates_used)) if usage_totals.rates_used is not None else None
        )
        self._conn.execute(
            "UPDATE steps SET "
            "usage_input_tokens = ?, usage_output_tokens = ?, usage_cache_read_tokens = ?, "
            "usage_cache_creation_tokens = ?, usage_cost_usd = ?, usage_cost_basis = ?, "
            "usage_rates_used = ?, "
            "usage_thinking_tokens = ?, turn_count = ? WHERE id = ?",
            (usage_totals.input_tokens, usage_totals.output_tokens,
             usage_totals.cache_read_tokens, usage_totals.cache_creation_tokens,
             usage_totals.cost_usd.to_usd(), usage_totals.cost_basis, rates_used_json,
             usage_totals.thinking_tokens, turn_count, step_id),
        )
        self._conn.execute("DELETE FROM step_tool_usage WHERE step = ?", (step_id,))
        for tool, usage in tool_usage_totals.items():
            self._conn.execute(
                "INSERT INTO step_tool_usage (step, tool, calls, bytes) VALUES (?, ?, ?, ?)",
                (step_id, tool, usage.calls, usage.bytes),
            )
        self._commit()
