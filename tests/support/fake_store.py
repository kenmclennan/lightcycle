import copy
import datetime
import os
import uuid
from contextlib import contextmanager
from dataclasses import replace

from lightcycle.ports.store import (
    ItemTextRow,
    NodeNotFoundError,
    ProjectEntry,
    ProjectResolutionError,
    StorePort,
)
from lightcycle.domain.pool import ToolUsage
from lightcycle.domain.runs import Pass, PhaseRun, pass_id, run_id
from lightcycle.domain.work import (
    Artifact, Item, NodeView, Park, State, Step, default_kind_for, derive_state,
    merge_condition_note,
)

_RAW_STORAGE_STATE = {
    State.BACKLOGGED: "backlogged",
    State.BLOCKED: "backlogged",
    State.QUEUED: "ready",
    State.WAITING: "ready",
    State.RUNNING: "in_progress",
    State.DONE: "done",
}


def _new_id():
    suffix = uuid.uuid4().hex[:8]
    if suffix.isdigit():
        suffix = "a" + suffix[1:]
    return "fake-" + suffix


def _label_value(labels, prefix):
    for l in labels:
        if l.startswith(prefix):
            return l[len(prefix):]
    return None


def labels_for(*, role=None, step=None, project=None):
    parts = []
    if role:
        parts.append("for:%s" % role)
    if step:
        parts.append("step:%s" % step)
    if project:
        parts.append("project:%s" % project)
    return parts


def record_to_step(record, blocked_by=None):
    labels = record.get("labels") or []
    meta = record.get("metadata") or {}
    deps = record.get("dep_count") or 0
    role = _label_value(labels, "for:")
    return Step(
        id=record["id"],
        item=record.get("parent"),
        title=record.get("title", ""),
        stage=_label_value(labels, "step:"),
        pass_id=record.get("pass_id"),
        role=role,
        state=derive_state(
            "step", record.get("state") == "done", record.get("assignee"), deps, role, []
        ),
        claimed_by=record.get("assignee"),
        model=meta.get("model"),
        outcome=record.get("outcome"),
        notes=record.get("notes"),
        reflection=meta.get("reflection"),
        watched_step=meta.get("watched_step"),
        park=Park(
            reason=meta.get("reason"), needs=meta.get("needs"), tried=meta.get("tried")
        ),
        deps=deps,
        blocked_by=list(blocked_by or []),
        created_at=record.get("created_at"),
        fired_at=meta.get("fired_at"),
        closed_at=record.get("closed_at"),
        active_seconds=meta.get("active_seconds"),
        usage_input_tokens=meta.get("usage_input_tokens") or 0,
        usage_output_tokens=meta.get("usage_output_tokens") or 0,
        usage_cache_read_tokens=meta.get("usage_cache_read_tokens") or 0,
        usage_cache_creation_tokens=meta.get("usage_cache_creation_tokens") or 0,
        usage_cost_usd=meta.get("usage_cost_usd") or 0.0,
        usage_cost_basis=meta.get("usage_cost_basis"),
        usage_thinking_tokens=meta.get("usage_thinking_tokens"),
        turn_count=meta.get("turn_count") or 0,
    )


def record_to_item(record, blocked_by=None, child_states=()):
    meta = record.get("metadata") or {}
    blocked_by = list(blocked_by or [])
    return Item(
        id=record["id"],
        artifacts=tuple(Artifact.from_dict(a) for a in (meta.get("artifacts") or [])),
        title=record.get("title", ""),
        description=record.get("description"),
        state=derive_state(
            "item", record.get("state") == "done", None, bool(blocked_by), None,
            list(child_states),
        ),
        repo=record.get("repo"),
        project=_label_value(record.get("labels") or [], "project:"),
        workflow=record.get("workflow"),
        outcome=record.get("outcome"),
        disposition=record.get("disposition"),
        deps=record.get("dep_count") or 0,
        blocked_by=list(blocked_by or []),
        created_at=record.get("created_at"),
        closed_at=record.get("closed_at"),
    )


_TX_ATTRS = (
    "_records", "_labels", "_passes", "_runs", "_deps",
    "_history", "_projects", "_tool_usage", "_backfill_log", "_usage_accrual_state",
)


class FakeStore(StorePort):
    def __init__(self, now=None, config=None):
        self._records = {}
        self._labels = {}
        self._passes = []
        self._runs = []
        self._deps = {}
        self._history = {}
        self._projects = {}
        self._tool_usage = {}
        self._backfill_log = {}
        self._usage_accrual_state = {}
        self._now = now or (lambda: datetime.datetime.now().isoformat())
        self._config = config
        self._tx_depth = 0

    def bind_config(self, config):
        self._config = config

    @contextmanager
    def transaction(self):
        snapshot = {a: copy.deepcopy(getattr(self, a)) for a in _TX_ATTRS}
        self._tx_depth += 1
        try:
            yield
        except Exception:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                for a, v in snapshot.items():
                    setattr(self, a, v)
            raise
        else:
            self._tx_depth -= 1

    def _new_record(self, **fields):
        b = {
            "id": _new_id(),
            "title": "",
            "type": "step",
            "labels": [],
            "state": "ready",
            "assignee": None,
            "metadata": {},
            "parent": None,
            "dep_count": 0,
            "outcome": None,
            "notes": None,
            "closed_at": None,
            "description": None,
            "created_at": self._now(),
        }
        b.update(fields)
        return b

    def _get(self, tid):
        try:
            return self._records[tid]
        except KeyError:
            raise NodeNotFoundError("unknown node '%s'" % tid)

    def _blocked_by(self, tid):
        return [
            bid for bid in self._deps.get(tid, ())
            if bid in self._records and self._records[bid].get("state") != "done"
        ]

    def _to_step(self, record):
        return record_to_step(record, self._blocked_by(record["id"]))

    def _to_item(self, record):
        child_states = [
            self._to_step(r).state
            for r in self._records.values()
            if r.get("parent") == record["id"] and r.get("type") == "step"
        ]
        return record_to_item(record, self._blocked_by(record["id"]), child_states)

    def _to_node(self, record):
        if record.get("type") == "item":
            return self._to_item(record)
        return self._to_step(record)

    def item_artifacts(self, item_id):
        b = self._get(item_id)
        return [Artifact.from_dict(a) for a in ((b.get("metadata") or {}).get("artifacts") or [])]

    def add_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            self._get(item_id)["repo"] = value
            return
        b = self._get(item_id)
        meta = dict(b.get("metadata") or {})
        artifacts = list(meta.get("artifacts") or [])
        resolved_kind = kind if kind is not None else default_kind_for(atype)
        entry = {"type": atype, "value": value, "kind": resolved_kind}
        if label:
            entry["label"] = label
        if internal:
            entry["internal"] = internal
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        b["metadata"] = meta

    def replace_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        if atype == "repo":
            self._get(item_id)["repo"] = value
            return
        b = self._get(item_id)
        meta = dict(b.get("metadata") or {})
        artifacts = [
            a for a in (meta.get("artifacts") or [])
            if not (a.get("type") == atype and a.get("label") == label)
        ]
        resolved_kind = kind if kind is not None else default_kind_for(atype)
        entry = {"type": atype, "value": value, "kind": resolved_kind}
        if label:
            entry["label"] = label
        if internal:
            entry["internal"] = internal
        artifacts.append(entry)
        meta["artifacts"] = artifacts
        b["metadata"] = meta

    def all_nodes(self):
        return self.all_steps() + self.all_items()

    def all_nodes_including_done(self):
        return self.all_steps_including_done() + self.all_items_including_done()

    def all_items(self):
        return [self._to_item(b) for b in self._records.values()
                if b.get("type") == "item" and b.get("state") != "done"]

    def all_items_including_done(self):
        return [self._to_item(b) for b in self._records.values()
                if b.get("type") == "item"]

    def all_steps_including_done(self):
        return [self._to_step(b) for b in self._records.values()
                if b.get("type") == "step"]

    def item_text_rows(self):
        return [
            ItemTextRow(
                id=b["id"], title=b.get("title", ""),
                description=b.get("description"), notes=b.get("notes"),
            )
            for b in self._records.values()
            if b.get("type") == "item"
        ]

    def all_steps(self):
        return [self._to_step(b) for b in self._records.values()
                if b.get("type") == "step" and b.get("state") != "done"]

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
        record = self._get(tid)
        if record.get("type") != "item":
            raise NodeNotFoundError("unknown item '%s'" % tid)
        return self._to_item(record)

    def get_step(self, tid):
        record = self._get(tid)
        if record.get("type") != "step":
            raise NodeNotFoundError("unknown step '%s'" % tid)
        return self._to_step(record)

    def get_node(self, tid):
        return self._to_node(self._get(tid))

    def node_view(self, tid):
        t = self.get_node(tid)
        item = getattr(t, "item", None) or t.id
        arts = self.item_artifacts(item)
        return NodeView(step=t, item_artifacts=list(arts))

    def present_types(self, step):
        item = getattr(step, "item", None) or step.id
        present = {a.type for a in self.item_artifacts(item)}
        if self._get(item).get("repo"):
            present.add("repo")
        for run in self.open_runs_of(item):
            if run.branch:
                present.add("branch")
            if run.pr:
                present.add("pr")
        return present

    def reassign(self, tid, role):
        cur = getattr(self.get_node(tid), "role", None)
        if cur and cur != role:
            self.label_remove(tid, "for:%s" % cur)
        self.label_add(tid, "for:%s" % role)
        self.update_state(tid, State.WAITING if role == "human" else State.QUEUED)
        self.assign(tid, "")

    def route_to_human(self, tid, note):
        self.note(tid, note)
        self.reassign(tid, "human")

    def closed_items(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("state") != "done":
                continue
            result.append(
                {
                    "id": b["id"],
                    "title": b.get("title", ""),
                    "closed_at": b.get("closed_at"),
                    "outcome": b.get("outcome"),
                    "artifacts": [
                        Artifact.from_dict(a)
                        for a in ((b.get("metadata") or {}).get("artifacts") or [])
                    ],
                }
            )
        return result

    def ensure_store(self):
        pass

    def reclaim(self, tid):
        self.update_state(tid, State.QUEUED)
        self.assign(tid, "")

    def note(self, tid, text):
        b = self._get(tid)
        existing = b.get("notes")
        b["notes"] = (existing + "\n" + text) if existing else text

    def note_condition(self, tid, text):
        b = self._get(tid)
        b["notes"] = merge_condition_note(b.get("notes") or "", text, self._now())

    def set_notes(self, tid, text):
        self._get(tid)["notes"] = text or None

    def reopen(self, tid):
        b = self._get(tid)
        if b.get("state") != "done":
            return
        b["state"] = "in_progress"
        b["outcome"] = None
        b["closed_at"] = None

    def close(self, tid, reason, disposition=None):
        b = self._get(tid)
        if b.get("state") == "done":
            return
        b["state"] = "done"
        b["outcome"] = reason
        if b.get("type") == "item" and disposition is not None:
            b["disposition"] = disposition
        b["closed_at"] = datetime.datetime.now().isoformat()
        self._record_history(tid, State.DONE)
        for other_id, blockers in self._deps.items():
            if tid in blockers:
                other = self._records.get(other_id)
                if other and other.get("state") != "done":
                    other["dep_count"] = max(0, (other.get("dep_count") or 0) - 1)

    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        expected = expected_assignee or ""
        b = self._get(step)
        if b.get("state") == "done":
            return (False, None)
        assignee = b.get("assignee") or ""
        if expected and assignee and assignee != expected:
            return (False, None)
        self.close(step, outcome)
        new_id = None
        if next_step_spec is not None:
            new_id = self.create_step(**next_step_spec.as_kwargs())
        return (True, new_id)

    def disconnect(self):
        pass

    def update_metadata(self, tid, meta):
        b = self._get(tid)
        merged = dict(b.get("metadata") or {})
        merged.update(meta)
        b["metadata"] = merged

    def set_model(self, tid, model):
        b = self._get(tid)
        meta = dict(b.get("metadata") or {})
        meta["model"] = model
        b["metadata"] = meta

    def label_add(self, tid, label):
        b = self._records.get(tid)
        if b is not None:
            if label not in b["labels"]:
                b["labels"].append(label)
            return
        labels = self._labels.setdefault(tid, [])
        if label not in labels:
            labels.append(label)

    def label_remove(self, tid, label):
        b = self._records.get(tid)
        if b is not None:
            b["labels"] = [l for l in b["labels"] if l != label]
            return
        self._labels[tid] = [l for l in self._labels.get(tid, []) if l != label]

    def labels_of(self, tid):
        b = self._records.get(tid)
        if b is not None:
            return list(b.get("labels") or [])
        return list(self._labels.get(tid, []))

    def update_state(self, tid, state):
        self._get(tid)["state"] = _RAW_STORAGE_STATE.get(state, state)
        self._record_history(tid, state)

    def _record_history(self, tid, state):
        self._history.setdefault(tid, []).append((str(state), self._now()))

    def assign(self, tid, assignee):
        self._get(tid)["assignee"] = assignee or None

    def dep_add(self, node_id, blocked_by):
        if node_id not in self._deps:
            self._deps[node_id] = set()
        self._deps[node_id].add(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("state") != "done":
            b = self._get(node_id)
            b["dep_count"] = (b.get("dep_count") or 0) + 1

    def dep_remove(self, node_id, blocked_by):
        deps = self._deps.get(node_id)
        if not deps or blocked_by not in deps:
            return False
        deps.discard(blocked_by)
        blocker = self._records.get(blocked_by)
        if blocker and blocker.get("state") != "done":
            b = self._get(node_id)
            b["dep_count"] = max(0, (b.get("dep_count") or 0) - 1)
        return True

    def _ready_records(self):
        return [
            b
            for b in self._records.values()
            if b.get("state") == "ready"
            and not b.get("assignee")
            and not (b.get("dep_count") or 0)
            and b.get("type") == "step"
        ]

    def ready_steps(self):
        return [self._to_node(b) for b in self._ready_records()]

    def claim_ready(self, role):
        candidates = [
            b for b in self._ready_records() if "for:%s" % role in (b.get("labels") or [])
        ]
        if not candidates:
            return None
        b = candidates[0]
        spawn_id = self._config.spawn_id() if self._config else None
        b["assignee"] = spawn_id or role
        b["state"] = "in_progress"
        self._record_history(b["id"], State.RUNNING)
        return self._to_node(b)

    def accrue_active_seconds(self, step_ids, seconds):
        for tid in step_ids:
            b = self._records.get(tid)
            if b is None:
                continue
            meta = dict(b.get("metadata") or {})
            meta["active_seconds"] = (meta.get("active_seconds") or 0) + seconds
            b["metadata"] = meta

    def record_usage(self, tid, input_tokens, output_tokens, cache_read_tokens,
                      cache_creation_tokens, cost_usd, cost_basis, thinking_tokens):
        b = self._get(tid)
        meta = dict(b.get("metadata") or {})
        meta["usage_input_tokens"] = (meta.get("usage_input_tokens") or 0) + input_tokens
        meta["usage_output_tokens"] = (meta.get("usage_output_tokens") or 0) + output_tokens
        meta["usage_cache_read_tokens"] = (
            (meta.get("usage_cache_read_tokens") or 0) + cache_read_tokens
        )
        meta["usage_cache_creation_tokens"] = (
            (meta.get("usage_cache_creation_tokens") or 0) + cache_creation_tokens
        )
        meta["usage_cost_usd"] = (meta.get("usage_cost_usd") or 0.0) + cost_usd
        if cost_basis is not None:
            meta["usage_cost_basis"] = cost_basis
        if thinking_tokens is not None:
            meta["usage_thinking_tokens"] = (
                (meta.get("usage_thinking_tokens") or 0) + thinking_tokens
            )
        b["metadata"] = meta

    def record_attribution(self, tid, turn_count, tool_usage):
        b = self._get(tid)
        meta = dict(b.get("metadata") or {})
        meta["turn_count"] = (meta.get("turn_count") or 0) + turn_count
        b["metadata"] = meta
        for tool, usage in tool_usage.items():
            existing = self._tool_usage.get((tid, tool), ToolUsage())
            self._tool_usage[(tid, tool)] = ToolUsage(
                calls=existing.calls + usage.calls, bytes=existing.bytes + usage.bytes
            )

    def tool_usage_for(self, step_id):
        return {
            tool: usage for (tid, tool), usage in self._tool_usage.items() if tid == step_id
        }

    def usage_backfilled_logs(self):
        return set(self._backfill_log)

    def record_backfilled_usage(self, log_file, step_id, usage, attribution):
        if log_file in self._backfill_log:
            return False
        stored = step_id is not None and step_id in self._records
        if stored:
            self.record_usage(
                step_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                usage.cache_creation_tokens, usage.cost_usd, usage.cost_basis,
                usage.thinking_tokens,
            )
            self.record_attribution(step_id, attribution.turn_count, attribution.tool_usage)
        self._backfill_log[log_file] = (step_id, usage.has_result_line)
        return stored

    def record_live_usage(
        self, spawnid, log_file, offset, message_ids, pending_tool_use,
        posted_turn_count, posted_tool_usage, posted_input_tokens, posted_output_tokens,
        posted_cache_read_tokens, posted_cache_creation_tokens, posted_cost_usd,
        tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
        cost_usd, cost_basis, thinking_tokens, turn_count, tool_usage,
    ):
        self._usage_accrual_state[spawnid] = {
            "log_file": log_file,
            "offset": offset,
            "message_ids": list(message_ids),
            "pending_tool_use": dict(pending_tool_use),
            "posted_turn_count": posted_turn_count,
            "posted_tool_usage": dict(posted_tool_usage),
            "posted_input_tokens": posted_input_tokens,
            "posted_output_tokens": posted_output_tokens,
            "posted_cache_read_tokens": posted_cache_read_tokens,
            "posted_cache_creation_tokens": posted_cache_creation_tokens,
            "posted_cost_usd": posted_cost_usd,
        }
        if input_tokens or output_tokens or cache_read_tokens or cache_creation_tokens:
            self.record_usage(
                tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                cost_usd, cost_basis, thinking_tokens,
            )
        if turn_count or tool_usage:
            self.record_attribution(tid, turn_count, tool_usage)

    def usage_accrual_state(self, spawnid):
        state = self._usage_accrual_state.get(spawnid)
        return dict(state) if state is not None else None

    def clear_usage_accrual_state(self, spawnid):
        self._usage_accrual_state.pop(spawnid, None)

    def _seed_unclassified_backfill_row(self, log_file, step_id):
        self._backfill_log[log_file] = (step_id, None)

    def unclassified_backfill_logs(self):
        return [
            (log_file, step_id)
            for log_file, (step_id, had_result_line) in self._backfill_log.items()
            if had_result_line is None
        ]

    def reclassify_backfilled_log(self, log_file, step_id, usage, attribution):
        recovered = False
        if not usage.has_result_line and step_id is not None and step_id in self._records:
            self.record_usage(
                step_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                usage.cache_creation_tokens, usage.cost_usd, usage.cost_basis,
                usage.thinking_tokens,
            )
            recovered = True
        self._backfill_log[log_file] = (step_id, usage.has_result_line)
        return recovered

    def logs_for_step(self, step_id):
        return [
            log_file for log_file, (sid, _) in self._backfill_log.items() if sid == step_id
        ]

    def overwrite_usage_and_attribution(self, step_id, usage_totals, turn_count, tool_usage_totals):
        b = self._get(step_id)
        meta = dict(b.get("metadata") or {})
        meta["usage_input_tokens"] = usage_totals.input_tokens
        meta["usage_output_tokens"] = usage_totals.output_tokens
        meta["usage_cache_read_tokens"] = usage_totals.cache_read_tokens
        meta["usage_cache_creation_tokens"] = usage_totals.cache_creation_tokens
        meta["usage_cost_usd"] = usage_totals.cost_usd
        meta["usage_cost_basis"] = usage_totals.cost_basis
        meta["usage_thinking_tokens"] = usage_totals.thinking_tokens
        meta["turn_count"] = turn_count
        b["metadata"] = meta
        for key in [k for k in self._tool_usage if k[0] == step_id]:
            del self._tool_usage[key]
        for tool, usage in tool_usage_totals.items():
            self._tool_usage[(step_id, tool)] = usage

    def history(self, tid):
        return list(self._history.get(tid, []))

    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    id=None):
        if parent is None:
            parent = self.create_item(title, "an owning item")
        fields = dict(
            title=title,
            type="step",
            parent=parent,
            labels=labels_for(role=role, step=step),
        )
        if id is not None:
            fields["id"] = id
        b = self._new_record(**fields)
        tid = b["id"]
        self._records[tid] = b
        self._deps[tid] = set()
        if deps:
            for dep in deps:
                self.dep_add(tid, dep)
        return tid

    def edit_node(self, tid, *, title=None, description=None, goal=None, project=None,
                  parent=None, workflow=None):
        b = self._get(tid)
        if title is not None:
            b["title"] = title
        if description is not None:
            b["description"] = description
        if goal is not None:
            cur = self.get_node(tid).goal
            if cur:
                self.label_remove(tid, "goal:%s" % cur)
            if goal:
                self.label_add(tid, "goal:%s" % goal)
        if project is not None:
            cur = self.get_node(tid).project
            if cur:
                self.label_remove(tid, "project:%s" % cur)
            if project:
                self.label_add(tid, "project:%s" % project)
        if parent is not None:
            b["parent"] = parent
        if workflow is not None:
            b["workflow"] = workflow
        return tid

    def create_item(self, title, description, *, project=None, workflow=None, id=None,
                    shortcode=None):
        fields = dict(
            title=title,
            type="item",
            description=description,
            labels=labels_for(project=project),
            workflow=workflow,
            state="backlogged",
        )
        if id is not None:
            fields["id"] = id
        b = self._new_record(**fields)
        tid = b["id"]
        self._records[tid] = b
        return tid

    def open_pass(self, item):
        n = max([p.n for p in self._passes if p.item == item], default=0) + 1
        rec = Pass(pass_id(item, n), item, n, "open", "t0", None)
        self._passes.append(rec)
        return rec.id

    def current_pass(self, item):
        return next(
            (p for p in reversed(self._passes) if p.item == item and p.is_open), None
        )

    def get_pass(self, pid):
        return next((p for p in self._passes if p.id == pid), None)

    def passes_of(self, item):
        return [p for p in self._passes if p.item == item]

    def close_pass(self, pid):
        self._passes = [
            replace(p, state="closed", closed_at="t1") if p.id == pid and p.is_open else p
            for p in self._passes
        ]

    def open_run(self, item, pid, phase):
        rid = run_id(pid, phase)
        if not any(r.id == rid for r in self._runs):
            self._runs.append(PhaseRun(rid, item, pid, phase, opened_at="t0"))
        return rid

    def get_run(self, rid):
        return next((r for r in self._runs if r.id == rid), None)

    def current_run(self, item, phase):
        return next(
            (r for r in reversed(self._runs)
             if r.item == item and r.phase == phase and r.is_open),
            None,
        )

    def runs_of(self, item, pid=None):
        return [
            r for r in self._runs
            if r.item == item and (pid is None or r.pass_id == pid)
        ]

    def open_runs_of(self, item, pid=None):
        return [r for r in self.runs_of(item, pid) if r.is_open]

    def set_run_field(self, rid, **fields):
        allowed = {
            k: v for k, v in fields.items()
            if k in ("branch", "pr", "content_pin",
                     "comments_dispatched_through", "comments_handled_through")
        }
        if not allowed:
            return
        if "pr" in allowed and "content_pin" not in allowed:
            current = self.get_run(rid)
            if current is not None and current.pr != allowed["pr"]:
                allowed["content_pin"] = None
        self._runs = [replace(r, **allowed) if r.id == rid else r for r in self._runs]

    def close_run(self, rid, state="merged"):
        self._runs = [
            replace(r, state=state, closed_at="t1") if r.id == rid and r.is_open else r
            for r in self._runs
        ]

    def set_watched_step(self, tid, watched):
        meta = dict(self._get(tid).get("metadata") or {})
        meta["watched_step"] = watched
        self._get(tid)["metadata"] = meta

    def set_step_pass(self, tid, pid):
        self._get(tid)["pass_id"] = pid

    def children(self, item_id):
        return [self._to_node(b) for b in self._records.values() if b.get("parent") == item_id]

    def claimed_steps(self):
        return [self._to_node(b) for b in self._records.values() if b.get("state") == "in_progress"]

    def nodes_closed_since(self, since_date):
        result = []
        for b in self._records.values():
            if b.get("type") != "step" or b.get("state") != "done":
                continue
            closed_at = (b.get("closed_at") or "")[:10]
            if closed_at >= since_date:
                result.append(self._to_node(b))
        return result

    def closed_unretroed_items(self):
        result = []
        for b in self._records.values():
            if b.get("type") != "item" or b.get("state") != "done":
                continue
            labels = b.get("labels") or []
            if "retro-origin" in labels or "retroed" in labels:
                continue
            result.append(self._to_node(b))
        return result

    def closed_unretroed_passes(self):
        result = []
        for p in self._passes:
            if p.state != "closed":
                continue
            item_rec = self._records.get(p.item)
            if item_rec is None or item_rec.get("state") == "done":
                continue
            if "retro-origin" in self.labels_of(p.id) or "retroed" in self.labels_of(p.id):
                continue
            result.append(p)
        return result

    def last_n_closed_items(self, n):
        items = [
            b for b in self._records.values()
            if b.get("type") == "item" and b.get("state") == "done"
        ]
        items.sort(key=lambda b: b.get("closed_at") or "", reverse=True)
        return [self._to_node(b) for b in items[:n]]

    def steps_at_step(self, step):
        label = "step:%s" % step
        return [self._to_node(b) for b in self._records.values()
                if b.get("type") == "step" and label in (b.get("labels") or [])]

    def delete(self, tid):
        for other_id, blockers in self._deps.items():
            if tid in blockers:
                other = self._records.get(other_id)
                if other and other.get("state") != "done":
                    other["dep_count"] = max(0, (other.get("dep_count") or 0) - 1)
        self._records.pop(tid, None)
        self._deps.pop(tid, None)
        self._history.pop(tid, None)

    def add_project(self, identity, *, shortcode=None, local_path=None, remote=None):
        existing = self._projects.get(identity)
        merged = ProjectEntry(
            identity=identity,
            shortcode=shortcode if shortcode is not None else (existing.shortcode if existing else None),
            local_path=local_path if local_path is not None else (existing.local_path if existing else None),
            remote=remote if remote is not None else (existing.remote if existing else None),
        )
        self._projects[identity] = merged

    def get_project(self, identity):
        return self._projects.get(identity)

    def list_projects(self):
        return sorted(self._projects.values(), key=lambda p: p.identity)

    def remove_project(self, identity):
        if identity not in self._projects:
            raise KeyError("project not registered: %s" % identity)
        del self._projects[identity]

    def _match_projects(self, ref):
        rows = self.list_projects()
        if "/" in ref:
            return [p for p in rows if p.identity == ref]
        return [p for p in rows if p.identity.rsplit("/", 1)[-1] == ref]

    def find_project(self, ref):
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
        return matches[0]

    def resolve_project_path(self, ref):
        if os.path.isabs(ref):
            return ref
        project = self.find_project(ref)
        if not project.local_path:
            raise ProjectResolutionError(
                "project '%s' is registered but has no local checkout - activate the item to "
                "clone it automatically, or run `lc project add %s --path <dir>` to point at an "
                "existing one" % (project.identity, project.identity)
            )
        return project.local_path
