from lightcycle.domain.work.outputs import ArtifactRecord
from lightcycle.domain.work import Artifact, State, merge_condition_note
from lightcycle.ports.store import NodeNotFoundError
from lightcycle.adapters.sqlite.shared import _PARK_COLUMNS, _RAW_STORAGE_STATE


class StepsAggregate:
    def all_steps_including_done(self):
        return self._select_steps("")

    def all_steps(self):
        return self._select_steps("state != 'done'")

    def get_step(self, tid):
        rows = self._select_steps("id = ?", (tid,))
        if not rows:
            raise NodeNotFoundError("unknown step '%s'" % tid)
        return rows[0]

    def _blockers_of(self, tid):
        return [
            r[0] for r in self._conn.execute(
                "SELECT blocked_by FROM deps WHERE node_id = ?", (tid,)
            ).fetchall()
        ]

    def labels_of(self, tid):
        return [
            r[0] for r in self._conn.execute(
                "SELECT label FROM labels WHERE node_id = ?", (tid,)
            ).fetchall()
        ]

    def reclaim(self, tid):
        try:
            self._conn.execute(
                "UPDATE %s SET state = ?, assignee = NULL WHERE id = ?"
                % self._table_of(tid),
                (_RAW_STORAGE_STATE.get(State.QUEUED, State.QUEUED), tid),
            )
            self._record_history(tid, State.QUEUED)
            self._commit()
        except Exception:
            self._conn.rollback()
            raise

    def note(self, tid, text):
        row = self._conn.execute("SELECT notes FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        combined = (row[0] + "\n" + text) if row[0] else text
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (combined, tid))
        self._commit()

    def note_condition(self, tid, text):
        row = self._conn.execute("SELECT notes FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        combined = merge_condition_note(row[0] or "", text, self._now())
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (combined, tid))
        self._commit()

    def set_notes(self, tid, text):
        row = self._conn.execute("SELECT 1 FROM steps WHERE id = ?", (tid,)).fetchone()
        if row is None:
            raise NodeNotFoundError("unknown node '%s'" % tid)
        self._conn.execute("UPDATE steps SET notes = ? WHERE id = ?", (text or None, tid))
        self._commit()

    def complete_node(self, tid, reason, disposition=None, note=None):
        table = self._table_of(tid)
        if table == "items" and disposition is not None:
            self._conn.execute(
                "UPDATE items SET state = 'done', outcome = ?, disposition = ?, note = ?, "
                "closed_at = ? WHERE id = ? AND state != 'done'",
                (reason, disposition, note, self._now(), tid),
            )
        else:
            self._conn.execute(
                "UPDATE %s SET state = 'done', outcome = ?, closed_at = ? "
                "WHERE id = ? AND state != 'done'" % table,
                (reason, self._now(), tid),
            )
        self._record_history(tid, State.DONE)
        self._commit()

    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        expected = expected_assignee or ""
        cur = self._conn.execute(
            "UPDATE steps SET state = 'done', outcome = ?, closed_at = ? "
            "WHERE id = ? AND state != 'done' "
            "AND (? = '' OR (COALESCE(assignee, '') = '' AND claim_epoch = 0) OR assignee = ?)",
            (outcome, self._now(), step, expected, expected),
        )
        if cur.rowcount == 0:
            if self._tx_depth == 0:
                self._conn.rollback()
            return (False, None)
        try:
            self._record_history(step, State.DONE)
            new_id = None
            if next_step_spec is not None:
                new_id = self._insert_step_nocommit(**next_step_spec.as_kwargs())
            self._commit()
        except Exception:
            if self._tx_depth == 0:
                self._conn.rollback()
            raise
        return (True, new_id)

    def release(self):
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
        self._commit()

    def set_model(self, tid, model):
        self._conn.execute("UPDATE steps SET model = ? WHERE id = ?", (model, tid))
        self._commit()

    def label_add(self, tid, label):
        if not self._apply_label(tid, label, True):
            exists = self._conn.execute(
                "SELECT 1 FROM labels WHERE node_id = ? AND label = ?", (tid, label)
            ).fetchone()
            if not exists:
                self._conn.execute(
                    "INSERT INTO labels (node_id, label) VALUES (?, ?)", (tid, label)
                )
        self._commit()

    def label_remove(self, tid, label):
        if not self._apply_label(tid, label, False):
            self._conn.execute(
                "DELETE FROM labels WHERE node_id = ? AND label = ?", (tid, label)
            )
        self._commit()

    def update_state(self, tid, state):
        self._conn.execute(
            "UPDATE %s SET state = ? WHERE id = ?" % self._table_of(tid),
            (_RAW_STORAGE_STATE.get(state, state), tid),
        )
        self._record_history(tid, state)
        self._commit()

    def assign(self, tid, assignee):
        self._conn.execute(
            "UPDATE steps SET assignee = ? WHERE id = ?", (assignee or None, tid)
        )
        self._commit()

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
        self._commit()

    def dep_remove(self, node_id, blocked_by):
        cur = self._conn.execute(
            "DELETE FROM deps WHERE node_id = ? AND blocked_by = ?", (node_id, blocked_by)
        )
        self._commit()
        return cur.rowcount > 0

    def ready_steps(self):
        return self._select_steps(
            "state = 'ready' AND NOT EXISTS ("
            "  SELECT 1 FROM deps d LEFT JOIN steps b ON b.id = d.blocked_by "
            "  LEFT JOIN items bi ON bi.id = d.blocked_by "
            "  WHERE d.node_id = steps.id AND COALESCE(b.state, bi.state, 'ready') != 'done'"
            ")"
        )

    def claim_ready(self, role, assignee=None, item=None, stage=None, exclude=()):
        extra_sql = ""
        params = [role]
        excluded = list(exclude)
        if excluded:
            extra_sql += " AND id NOT IN (%s)" % ", ".join("?" * len(excluded))
            params.extend(excluded)
        if item is not None:
            extra_sql += " AND item = ?"
            params.append(item)
        if stage is not None:
            extra_sql += " AND stage = ?"
            params.append(stage)
        row = self._conn.execute(
            "SELECT id FROM steps WHERE state = 'ready' "
            "AND role = ?" + extra_sql + " AND NOT EXISTS ("
            "  SELECT 1 FROM deps d LEFT JOIN steps b ON b.id = d.blocked_by "
            "  LEFT JOIN items bi ON bi.id = d.blocked_by "
            "  WHERE d.node_id = steps.id AND COALESCE(b.state, bi.state, 'ready') != 'done'"
            ") LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            return None
        tid = row[0]
        assignee = assignee or role
        cur = self._conn.execute(
            "UPDATE steps SET assignee = ?, state = 'in_progress', claim_epoch = claim_epoch + 1 "
            "WHERE id = ? AND state = 'ready'",
            (assignee, tid),
        )
        if cur.rowcount == 0:
            self._commit()
            return None
        self._record_history(tid, State.RUNNING)
        self._commit()
        return self.get_node(tid)

    def _insert_step_nocommit(self, *, stage=None, role=None, item=None, deps=None,
                              id=None, previous=None):
        if item is None:
            raise ValueError("create_step requires an item")
        tid = self._mint_or_adopt(id, item)
        self._conn.execute(
            "INSERT INTO steps (id, item, stage, role, state, created_at, previous_step) "
            "VALUES (?, ?, ?, ?, 'ready', ?, ?)",
            (tid, item, stage, role, self._now(), previous),
        )
        if deps:
            for dep in deps:
                self._dep_add_nocommit(tid, dep)
        return tid

    def create_step(self, *, stage=None, role=None, item=None, deps=None,
                    id=None, previous=None):
        tid = self._insert_step_nocommit(
            stage=stage, role=role, item=item, deps=deps, id=id, previous=previous)
        self._commit()
        return tid

    def set_report(self, step, text):
        if self._conn.execute(
            "UPDATE steps SET report = ? WHERE id = ?", (text or None, step)
        ).rowcount == 0:
            raise NodeNotFoundError("unknown step '%s'" % step)
        self._commit()

    def set_log(self, step, path):
        if self._conn.execute(
            "UPDATE steps SET log_path = ? WHERE id = ?", (path or None, step)
        ).rowcount == 0:
            raise NodeNotFoundError("unknown step '%s'" % step)
        self._commit()

    def save_step_inputs(self, step, frozen_at, body):
        self._conn.execute(
            "INSERT INTO step_inputs (step, frozen_at, body) VALUES (?, ?, ?) "
            "ON CONFLICT(step) DO UPDATE SET frozen_at = excluded.frozen_at, body = excluded.body",
            (step, frozen_at, body),
        )
        self._commit()

    def step_inputs(self, step):
        row = self._conn.execute(
            "SELECT frozen_at, body FROM step_inputs WHERE step = ?", (step,)
        ).fetchone()
        return None if row is None else (row[0], row[1])

    def artifact_log(self, item_id):
        rows = self._conn.execute(
            "SELECT a.item_id, a.rowid, a.atype, a.value, a.label, a.internal, a.kind "
            "FROM artifacts a WHERE a.item_id = ? "
            "OR a.item_id IN (SELECT id FROM steps WHERE item = ?) ORDER BY a.rowid",
            (item_id, item_id),
        ).fetchall()
        return [
            ArtifactRecord(
                node_id=r[0], seq=r[1],
                artifact=Artifact(
                    type=r[2], value=r[3], label=r[4], internal=bool(r[5]), kind=r[6]),
            )
            for r in rows
        ]

    def claimed_steps(self):
        return self._select_steps("state = 'in_progress'")

    def history(self, tid):
        rows = self._conn.execute(
            "SELECT state, ts FROM history WHERE node_id = ? ORDER BY seq ASC", (tid,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def waiting_history(self):
        rows = self._conn.execute(
            "SELECT node_id, ts FROM history WHERE state = 'waiting'"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def steps_at_step(self, step):
        return self._select_steps("stage = ?", (step,))
