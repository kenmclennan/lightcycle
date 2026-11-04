from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.claim_step import ClaimInput
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.release_stacked_items import ReleaseStackedItemsUseCase
from lightcycle.application.pool.restack_stacks import RestackStacksUseCase
from lightcycle.domain.flow.simulate_plan import merge_gate_stages, shortest_path_to_stage
from lightcycle.domain.runs import RunState
from lightcycle.domain.work.state import State

_MAX_TICKS = 4
_MAX_TAIL = 20


def _line(slice_no, name, expected, found):
    return "stack: slice %d (%s): expected %s, %s" % (slice_no, name, expected, found)


class StackSimulation:
    def __init__(self, store, flow, worktrees, claim, complete, git, github, projects_root,
                 seed_item, synthesize, monitor, terminal_outcome):
        self._store = store
        self._flow = flow
        self._claim = claim
        self._complete = complete
        self._recorder = git
        self._scripted = github
        self._projects_root = projects_root
        self._seed_item = seed_item
        self._synthesize = synthesize
        self._monitor = monitor
        self._terminal_outcome = terminal_outcome
        self._release = ReleaseStackedItemsUseCase(store, flow)
        self._restack = RestackStacksUseCase(
            store, git, github, worktrees, flow, complete, lambda pr: None)
        self.violations = []
        self.trace = []

    def run(self, pin, graph, count):
        before = len(self._store.all_items_including_done())
        item = self._seed_item(pin, graph)
        names = ["slice-%d" % i for i in range(1, count + 1)]
        self._store.add_artifact(item, graph.slices_artifact, "\n".join(names))
        self._pin, self._graph, self._item, self._names = pin, graph, item, names
        self._default = self._recorder.worktree_base(self._projects_root)
        if not self._plan_paths():
            return
        self._enter_phase()
        if self.violations:
            return
        self._build()
        if self.violations:
            return
        self._rework()
        if self.violations:
            return
        self._merge_bottom_up()
        if self.violations:
            return
        self._cleanup_check()
        if len(self._store.all_items_including_done()) != before + 1:
            self.violations.append(
                "stack: expected no item created beyond the scenario's own, found %d new"
                % (len(self._store.all_items_including_done()) - before))

    def _plan_paths(self):
        graph = self._graph
        phase = graph.sliced_phase
        first, self._entry_path = shortest_path_to_stage(
            graph, graph.entry, lambda s: graph.phase_for(s) == phase)
        if first is None or not self._entry_path:
            self.violations.append(
                "stack: no path from the entry stage into the sliced phase '%s'" % phase)
            return False
        self._first = first
        gates = merge_gate_stages(graph)
        gate, self._slice_path = shortest_path_to_stage(graph, first, lambda s: s in gates)
        if gate is None:
            self.violations.append(
                "stack: no path from the sliced phase's first stage to a pr_merge gate")
            return False
        self._gate = gate
        sd = self._flow.load_flow(self._pin).step_def(gate)
        self._merge_outcome = sd.pr_merge
        self._merge_target = (graph.edges.get(gate) or {}).get(sd.pr_merge)
        return True

    def _claim_stage(self, stage, slice_no, name):
        role = self._flow.owner_of(stage, self._pin)
        resp = self._claim.execute(ClaimInput(role=role, item=self._item, stage=stage))
        if resp is None:
            self.violations.append(_line(
                slice_no, name, "a ready '%s' step to claim" % stage, "none was ready"))
            return None
        step = resp.view.step
        if slice_no and step.slice != slice_no:
            self.violations.append(_line(
                slice_no, name, "the '%s' claim to be its own step" % stage,
                "the claim was slice %d's" % step.slice))
            return None
        return resp

    def _complete_stage(self, step, outcome, slice_no, name):
        try:
            self._complete.execute(CompleteInput(step=step.id, outcome=outcome))
        except UseCaseError as e:
            self.violations.append(_line(
                slice_no, name, "'%s' to complete with %s" % (step.stage, outcome),
                "it raised: %s" % e))
            return False
        return True

    def _enter_phase(self):
        for planned in self._entry_path:
            resp = self._claim_stage(planned.stage, 0, "entry")
            if resp is None:
                return
            self._synthesize(self._item, self._pin, planned.stage, 0)
            if not self._complete_stage(resp.view.step, planned.outcome, 0, "entry"):
                return

    def _runs(self):
        current = self._store.current_pass(self._item)
        runs = self._store.runs_of(self._item, current.id) if current else []
        by_slice = {}
        for run in runs:
            if run.slice > 0 and run.phase == self._graph.sliced_phase:
                by_slice[run.slice] = run
        return by_slice

    def _slice_steps(self, slice_no):
        return [
            s for s in self._store.children(self._item)
            if s.type == "step" and s.slice == slice_no and s.state != State.DONE
        ]

    def _drive(self, slice_no, name, path):
        for planned in path:
            resp = self._claim_stage(planned.stage, slice_no, name)
            if resp is None:
                return None
            self._synthesize(self._item, self._pin, planned.stage, slice_no)
            self._open_pr_if_ready(slice_no, name, resp)
            if not self._complete_stage(resp.view.step, planned.outcome, slice_no, name):
                return None
            self._tick()
        return True

    def _open_pr_if_ready(self, slice_no, name, resp):
        run = self._runs().get(slice_no)
        if run is None or not run.pr or run.pr in self._opened:
            return
        stack = resp.surface.get("stack")
        base = stack["branch"] if stack else self._default
        self._scripted.open_pr(run.pr, base)
        self._opened.add(run.pr)

    def _tick(self):
        self._release.execute()
        self._restack.execute()
        self._monitor.execute()
        for run in self._runs().values():
            if run.pr in self._opened and run.branch:
                self._scripted.script_head(run.pr, self._recorder.ref_sha(self._projects_root, run.branch))

    def _quiesce(self):
        for _ in range(_MAX_TICKS):
            self._tick()

    def _build(self):
        self._opened = set()
        self._claimed_while_open = {}
        for k, name in enumerate(self._names, start=1):
            if k > 1:
                lower = self._runs().get(k - 1)
                self._claimed_while_open[k] = lower is not None and lower.state == RunState.OPEN
            if self._drive(k, name, self._slice_path) is None:
                return
        self._check_build()

    def _check_build(self):
        runs = self._runs()
        for k, name in enumerate(self._names, start=1):
            run = runs.get(k)
            if run is None or not run.pr:
                self.violations.append(_line(k, name, "a PR to be opened", "no PR on the run"))
                continue
            expected = self._default if k == 1 else runs[k - 1].branch
            found = self._scripted.base_of(run.pr)
            if found != expected:
                self.violations.append(_line(
                    k, name, "its PR opened against %s" % expected, "it was opened against %s" % found))
            if k > 1 and not self._claimed_while_open.get(k):
                self.violations.append(_line(
                    k, name, "building to start before slice %d merged" % (k - 1),
                    "slice %d was already merged" % (k - 1)))
        self._check_gates_single()
        self._check_edits(0)
        for k, name in enumerate(self._names, start=1):
            run = runs.get(k)
            if run is not None:
                self.trace.append("stack: slice %d %s branch %s base %s pr %s" % (
                    k, name, run.branch, self._scripted.base_of(run.pr), run.pr))

    def _gate_steps(self, slice_no):
        return [
            s for s in self._store.children(self._item)
            if s.type == "step" and s.slice == slice_no and s.stage == self._gate
        ]

    def _check_gates_single(self):
        for k, name in enumerate(self._names, start=1):
            open_gates = [s for s in self._gate_steps(k) if s.state != State.DONE]
            if len(open_gates) > 1:
                self.violations.append(_line(
                    k, name, "at most one open merge gate", "found %d" % len(open_gates)))

    def _settle(self):
        for k, name in enumerate(self._names, start=1):
            steps = self._slice_steps(k)
            if len(steps) != 1 or steps[0].stage == self._gate:
                continue
            if steps[0].stage == self._merge_target:
                continue
            stage, path = shortest_path_to_stage(
                self._graph, steps[0].stage, lambda s: s == self._gate)
            if stage is None:
                self.violations.append(_line(
                    k, name, "a path from '%s' back to the merge gate" % steps[0].stage,
                    "none exists"))
                return
            if self._drive(k, name, path) is None:
                return
        self._check_gates_single()

    def _calls_since(self, mark):
        return self._recorder.restack_calls()[mark:]

    def _slice_of_branch(self):
        return {r.branch: k for k, r in self._runs().items() if r.branch}

    def _check_restack(self, calls, expected, label, first_onto):
        by_branch = self._slice_of_branch()
        listed_all = [by_branch.get(st.branch) for call in calls for st in call]
        reported = False
        for k in expected:
            if k not in listed_all:
                reported = True
                self.violations.append(_line(
                    k, self._names[k - 1], "%s to restack it" % label,
                    "no restack call listed it"))
        for k in listed_all:
            if k not in expected and k is not None:
                reported = True
                self.violations.append(_line(
                    k, self._names[k - 1], "%s not to restack it" % label,
                    "a restack call listed it"))
        if reported:
            return
        if len(calls) > 1:
            self.violations.append(
                "stack: %s expected one restack call, found %d" % (label, len(calls)))
            return
        if not calls:
            return
        steps = list(calls[0])
        listed = [by_branch.get(st.branch) for st in steps]
        if listed != expected:
            culprit = next(k for k, want in zip(listed, expected) if k != want)
            self.violations.append(_line(
                culprit, self._names[culprit - 1],
                "%s to restack slices %s bottom-up" % (label, expected),
                "it listed slices %s" % listed))
            return
        for i, step in enumerate(steps):
            if i == 0:
                want = " or ".join(first_onto)
                ok = step.onto in first_onto
            else:
                want = steps[i - 1].branch
                ok = step.onto == want
            if not ok:
                k = listed[i]
                self.violations.append(_line(
                    k, self._names[k - 1], "%s to restack onto %s" % (label, want),
                    "it was onto %s" % step.onto))

    def _rework(self):
        count = len(self._names)
        runs = self._runs()
        low = runs[1]
        mark = len(self._recorder.restack_calls())
        edits = len(self._scripted.base_edits)
        self._recorder.set_tip(low.branch, "sim-reworked")
        self._scripted.script_head(low.pr, "sim-reworked")
        self._quiesce()
        self._settle()
        if self.violations:
            return
        self._check_restack(
            self._calls_since(mark), list(range(2, count + 1)) if count > 1 else [],
            "the rework", ("origin/" + low.branch,))
        self._check_edits(edits)
        self.trace.append("stack: rework slice 1 restacked slices 2..%d" % count)

    def _merge_bottom_up(self):
        count = len(self._names)
        for k, name in enumerate(self._names, start=1):
            runs = self._runs()
            run = runs[k]
            mark = len(self._recorder.restack_calls())
            edits = len(self._scripted.base_edits)
            self._scripted.script_merged(run.pr)
            self._quiesce()
            self._settle()
            if self.violations:
                return
            above = list(range(k + 1, count + 1))
            self._check_restack(
                self._calls_since(mark), above, "the merge of slice %d" % k,
                (self._default, "origin/" + self._default))
            self._check_edits(edits)
            closed = self._store.get_node(self._item).state == State.DONE
            if k < count and closed:
                self.violations.append(_line(
                    k, name, "the item to stay open until slice %d merged" % count,
                    "the item closed"))
                return
            if k < count:
                self.trace.append("stack: merge slice %d retargeted slice %d" % (k, k + 1))
        self._finish_tail()

    def _check_edits(self, start):
        runs = self._runs()
        slice_of_pr = {r.pr: k for k, r in runs.items() if r.pr}
        for pr, base, merged in self._scripted.base_edits[start:]:
            k = slice_of_pr.get(pr)
            if k is None:
                continue
            lower = runs.get(k - 1)
            if base != self._default:
                self.violations.append(_line(
                    k, self._names[k - 1], "its PR retargeted to %s" % self._default,
                    "it was retargeted to %s" % base))
            elif lower is not None and lower.pr not in merged:
                self.violations.append(_line(
                    k, self._names[k - 1],
                    "its PR retargeted only after slice %d merged" % (k - 1),
                    "it was retargeted before slice %d merged" % (k - 1)))

    def _finish_tail(self):
        for _ in range(_MAX_TAIL):
            if self._store.get_node(self._item).state == State.DONE:
                return
            open_steps = [
                s for s in self._store.children(self._item)
                if s.type == "step" and s.state != State.DONE
            ]
            if not open_steps:
                break
            step = open_steps[0]
            if not self._flow.owner_of(step.stage, self._pin):
                break
            resp = self._claim.execute(ClaimInput(
                role=step.role, item=self._item, stage=step.stage))
            if resp is None:
                self.violations.append(
                    "stack: expected a ready '%s' step after the last merge, none was ready"
                    % step.stage)
                return
            self._synthesize(self._item, self._pin, step.stage, 0)
            outcome = self._terminal_outcome(self._graph, step.stage)
            if not self._complete_stage(resp.view.step, outcome, 0, "tail"):
                return
        if self._store.get_node(self._item).state != State.DONE:
            self.violations.append(
                "stack: expected the item to close after the last slice merged, it stayed open")

    def _cleanup_check(self):
        for k, name in enumerate(self._names, start=1):
            merged = [
                s for s in self._gate_steps(k)
                if s.state == State.DONE and s.outcome == self._merge_outcome
            ]
            if len(merged) != 1:
                self.violations.append(_line(
                    k, name, "one merge gate completed with %s" % self._merge_outcome,
                    "found %d" % len(merged)))
        ran = [
            s for s in self._store.children(self._item)
            if s.type == "step" and s.stage == self._merge_target and s.state == State.DONE
        ]
        if len(ran) != 1:
            self.violations.append(
                "stack: expected '%s' to run exactly once, it ran %d times"
                % (self._merge_target, len(ran)))
            return
        self.trace.append("stack: cleanup ran once")
