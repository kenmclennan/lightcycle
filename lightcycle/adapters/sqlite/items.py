from lightcycle.domain.feedback import RETRO_ORIGIN_LABEL, RETROED_LABEL
from lightcycle.domain.runs import Pass
from lightcycle.domain.work import Artifact, NodeView, default_kind_for
from lightcycle.ports.store import ItemText, NodeNotFoundError
from lightcycle.adapters.sqlite.shared import _ITEM_COLUMNS, _STEP_COLUMNS


class ItemsAggregate:
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

    def artifacts_of_type(self, atype):
        rows = self._conn.execute(
            "SELECT item_id, value, label, internal, kind FROM artifacts "
            "WHERE atype = ? ORDER BY rowid",
            (atype,),
        ).fetchall()
        return [
            (r[0], Artifact(type=atype, value=r[1], label=r[2], internal=bool(r[3]), kind=r[4]))
            for r in rows
        ]

    def default_kind_for(self, atype):
        return default_kind_for(atype, context_types=self._config.context_artifact_types())

    def _set_repo(self, item_id, value):
        self._conn.execute("UPDATE items SET repo = ? WHERE id = ?", (value, item_id))
        self._commit()

    def add_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            return self._set_repo(item_id, value)
        resolved_kind = kind if kind is not None else self.default_kind_for(atype)
        self._conn.execute(
            "INSERT INTO artifacts (item_id, atype, value, label, internal, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, atype, value, label, internal, resolved_kind),
        )
        self._commit()

    def replace_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            return self._set_repo(item_id, value)
        resolved_kind = kind if kind is not None else self.default_kind_for(atype)
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
        self._commit()

    def remove_artifact(self, item_id, atype):
        self._conn.execute(
            "DELETE FROM artifacts WHERE item_id = ? AND atype = ?", (item_id, atype)
        )
        self._commit()

    def all_nodes(self):
        return self.all_steps() + self.all_items()

    def all_nodes_including_done(self):
        return self.all_steps_including_done() + self.all_items_including_done()

    def all_items(self):
        return self._select_items("state != 'done'")

    def all_items_including_done(self):
        return self._select_items("")

    def items_with_label(self, label):
        return self._select_items(
            "id IN (SELECT node_id FROM labels WHERE label = ?)", (label,))

    def item_texts(self):
        rows = self._conn.execute(
            "SELECT id, title, description, NULL FROM items"
        ).fetchall()
        return [ItemText(*row) for row in rows]

    def type_of(self, tid):
        try:
            self.get_step(tid)
            return "step"
        except NodeNotFoundError:
            pass
        try:
            self.get_item(tid)
            return "item"
        except NodeNotFoundError:
            return None

    def get_item(self, tid):
        rows = self._select_items("id = ?", (tid,))
        if not rows:
            raise NodeNotFoundError("unknown item '%s'" % tid)
        return rows[0]

    def item_workflow(self, item_id):
        row = self._conn.execute("SELECT workflow FROM items WHERE id = ?", (item_id,)).fetchone()
        return row[0] if row else None

    def get_node(self, tid):
        rows = self._select_steps("id = ?", (tid,))
        if rows:
            return rows[0]
        return self.get_item(tid)

    def node_view(self, tid):
        t = self.get_node(tid)
        item = getattr(t, "item", None) or t.id
        arts = self.item_artifacts(item)
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

    def closed_items(self):
        return self._select_items("state = 'done'")

    def snapshot_nodes(self):
        result = []
        for row in self._conn.execute(
            "SELECT %s FROM items ORDER BY rowid" % ", ".join(_ITEM_COLUMNS)
        ).fetchall():
            d = dict(zip(_ITEM_COLUMNS, row))
            result.append(dict(d, type="item", artifacts=[
                a.as_dict() for a in self.item_artifacts(d["id"])
            ], blocked_by=self._blockers_of(d["id"]), labels=self.labels_of(d["id"])))
        for row in self._conn.execute(
            "SELECT %s FROM steps ORDER BY rowid" % ", ".join(_STEP_COLUMNS)
        ).fetchall():
            d = dict(zip(_STEP_COLUMNS, row))
            result.append(dict(d, type="step", blocked_by=self._blockers_of(d["id"]),
                               labels=self.labels_of(d["id"])))
        return result

    def reopen(self, tid):
        self._conn.execute(
            "UPDATE %s SET state = 'in_progress', outcome = NULL, closed_at = NULL "
            "WHERE id = ? AND state = 'done'" % self._table_of(tid),
            (tid,),
        )
        self._commit()

    def edit_node(self, tid, *, title=None, description=None, project=None,
                  workflow=None):
        table = self._table_of(tid)
        allowed = () if table == "steps" else (
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
        self._commit()
        return tid

    def create_item(self, title, description, *, project=None, workflow=None, id=None,
                    shortcode=None):
        tid = self._mint_or_adopt(id, None, shortcode=shortcode)
        self._conn.execute(
            "INSERT INTO items (id, title, description, state, project, workflow, created_at) "
            "VALUES (?, ?, ?, 'backlogged', ?, ?, ?)",
            (tid, title, description, project, workflow, self._now()),
        )
        self._commit()
        return tid

    def children(self, item_id):
        return self._select_steps("item = ?", (item_id,))

    def nodes_closed_since(self, since_date):
        return self._select_steps(
            "state = 'done' AND substr(closed_at, 1, 10) >= ?", (since_date,)
        )

    def closed_unretroed_items(self):
        return self._select_items(
            "state = 'done' "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = ?) "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = ?)",
            (RETRO_ORIGIN_LABEL, RETROED_LABEL),
        )

    def closed_unretroed_passes(self):
        rows = self._conn.execute(
            "SELECT id, item, n, state, opened_at, closed_at FROM passes "
            "WHERE state = 'closed' "
            "AND item IN (SELECT id FROM items WHERE state != 'done') "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = ?) "
            "AND id NOT IN (SELECT node_id FROM labels WHERE label = ?)",
            (RETRO_ORIGIN_LABEL, RETROED_LABEL),
        ).fetchall()
        return [Pass(*r) for r in rows]

    def last_n_closed_items(self, n):
        return self._select_items(
            "state = 'done'", params=(n,), suffix="ORDER BY closed_at DESC LIMIT ?"
        )

    def delete(self, tid):
        self._conn.execute("DELETE FROM steps WHERE id = ?", (tid,))
        self._conn.execute("DELETE FROM step_gh_calls WHERE step = ?", (tid,))
        self._conn.execute("DELETE FROM step_tool_usage WHERE step = ?", (tid,))
        self._conn.execute("DELETE FROM items WHERE id = ?", (tid,))
        self._conn.execute("DELETE FROM deps WHERE node_id = ? OR blocked_by = ?", (tid, tid))
        self._conn.execute("DELETE FROM artifacts WHERE item_id = ?", (tid,))
        self._conn.execute("DELETE FROM labels WHERE node_id = ?", (tid,))
        self._conn.execute("DELETE FROM history WHERE node_id = ?", (tid,))
        self._conn.execute("DELETE FROM review_escapes WHERE item = ?", (tid,))
        self._conn.execute("DELETE FROM phase_runs WHERE item = ?", (tid,))
        self._conn.execute("DELETE FROM passes WHERE item = ?", (tid,))
        self._commit()
