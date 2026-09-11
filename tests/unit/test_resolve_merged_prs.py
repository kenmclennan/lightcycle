import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool.check_content_pin import CheckContentPinUseCase
from lightcycle.application.pool.pr_lookups import latest_step
from lightcycle.application.pool.resolve_merged_prs import ResolveMergedPrsUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.domain.work import State
from tests.support.fake_fs import FakeFs, flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.support.step_factory import create_owned_step


def plant_pr(store, item, url, phase=None, branch=None, n=1, state="open"):
    while store.current_pass(item) is None or store.current_pass(item).n < n:
        current = store.current_pass(item)
        if current is not None:
            store.close_pass(current.id)
        store.open_pass(item)
    rid = store.open_run(item, store.current_pass(item).id, phase)
    store.set_branch(rid, branch)
    store.set_pr(rid, url)
    if state != "open":
        store.close_run(rid, state)
    return rid


class _FlowAdapter:
    def __init__(self, flow):
        self._flow = flow

    def workflow_for(self, step):
        return "wf"

    def project_for(self, step):
        return None

    def load_flow(self, name=None, project=None):
        return self._flow

    def flow_for(self, node):
        return self._flow

    def flow_next(self, step, outcome, name=None, project=None):
        return self._flow.next(step, outcome)

    def outcomes_for(self, step, name=None, project=None):
        return sorted(self._flow.step_def(step).routes.keys())

    def meta_for_step(self, step, name=None, project=None):
        return {}

    def owner_of(self, step, name=None, project=None):
        return self._flow.step_def(step).owner

    def ci_failed_cap_outcome(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.outcome if cap else None

    def ci_failed_cap_n(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.n if cap else None

    def ci_failed_cap_target(self, step, name=None, project=None):
        cap = self._flow.step_def(step).ci_cap
        return cap.target if cap else None

    def effective_transition(self, transition, outcome, prior_count, name=None, project=None):
        return self._flow.effective_transition(transition, outcome, prior_count)

    def phase_for(self, node):
        return self._flow.step_def(getattr(node, "stage", None)).phase

    def phase_for_stage(self, stage, name=None):
        return "code"

    def ends_pass(self, stage, outcome, name=None):
        return False


_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        }
    },
    disposition={"merged": "completed", "abandoned": "aborted"},
)

_MERGE_ONLY_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build"},
            "on_pr_merge": "merged",
        }
    },
    disposition={"merged": "completed"},
)

_CLOSE_ROUTES_TO_HUMAN_GATE_FLOW = flow_from_metas(
    {
        "confirm-abandon": {
            "step": "confirm-abandon",
        },
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "changes": "build", "abandoned": "confirm-abandon"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        },
    }
)


class FakeWorktrees:
    def release_run(self, run, delete_remote=True):
        self.released = getattr(self, "released", [])
        self.released.append(run.id)

    def __init__(self):
        self.removed = []

    def remove(self, item):
        self.removed.append(item)


class _TripwireFlow:
    def workflow_for(self, node):
        raise AssertionError("resolved the flow for a PR-less item")

    def flow_for(self, node):
        raise AssertionError("resolved the flow for a PR-less item")

    def load_flow(self, name=None):
        raise AssertionError("loaded the flow for a PR-less item")


class TestMonitorPrsSkipsPrlessItems(unittest.TestCase):
    def test_backlogged_item_with_an_inherited_selector_is_never_flow_resolved(self):
        store = FakeStore()
        store.create_item("backlog", "a description", workflow="lightcycle/spec-driven")
        _gh = FakeGitHub()
        uc = ResolveMergedPrsUseCase(
            store, _gh, FakeWorktrees(), _TripwireFlow(), None, CheckContentPinUseCase(store, _gh)
        )
        result = uc.execute()
        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])




class TestMonitorPrsMultiWorkflow(unittest.TestCase):
    def test_merge_reason_is_resolved_per_item_workflow(self):
        fs = FakeFs(
            metas={},
            workflow={
                "standard": (
                    "entry: write-code\n\n"
                    "edges:\n"
                    "  write-code   done    open-pr\n"
                    "  open-pr      done    await-merge\n"
                    "  await-merge  changes write-code\n\n"
                    "hooks:\n"
                    "  pr_merge   await-merge  merged\n"
                    "  pr_close   await-merge  abandoned\n\n"
                    "disposition:\n"
                    "  merged     completed\n"
                    "  abandoned  aborted\n"
                ),
                "spec": (
                    "entry: spec-writer\n\n"
                    "edges:\n"
                    "  spec-writer  done    open-pr\n"
                    "  open-pr      done    await-merge\n"
                    "  await-merge  changes spec-writer\n\n"
                    "hooks:\n"
                    "  pr_merge   await-merge  spec-merged\n"
                    "  pr_close   await-merge  abandoned\n\n"
                    "disposition:\n"
                    "  spec-merged  completed\n"
                    "  abandoned    aborted\n"
                ),
            },
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)

        code_item = store.create_item("code feature", "a description", workflow="standard")
        code_url = "https://github.com/x/y/pull/100"
        plant_pr(store, code_item, code_url)
        store.create_step(
            "await-merge: code feature", step="await-merge", role="human", parent=code_item
        )

        spec_item = store.create_item("a spec", "a description", workflow="spec")
        spec_url = "https://github.com/x/y/pull/101"
        plant_pr(store, spec_item, spec_url)
        store.create_step(
            "await-merge: a spec", step="await-merge", role="human", parent=spec_item
        )

        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={code_url, spec_url})
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, None, CheckContentPinUseCase(store, github)
        )

        result = uc.execute()

        self.assertEqual(set(result.merged), {code_item, spec_item})
        self.assertEqual(store.get_node(code_item).outcome, "merged")
        self.assertEqual(store.get_node(spec_item).outcome, "spec-merged")


_SPEC_DRIVEN = (
    "entry: spec-writer\n\n"
    "requires: brief repo\n\n"
    "workspace:\n"
    "  spec-await-merge  specs\n\n"
    "phase:\n"
    "  spec-writer       spec\n"
    "  spec-await-merge  spec\n"
    "  write-code        code\n"
    "  code-open-pr      code\n"
    "  code-await-merge  code\n\n"
    "nodes:\n"
    "  write-code        coder\n"
    "  spec-await-merge  await-merge\n"
    "  code-await-merge  await-merge\n\n"
    "edges:\n"
    "  spec-await-merge  spec-merged  write-code\n"
    "  spec-await-merge  changes      spec-writer\n"
    "  write-code        done         code-open-pr\n"
    "  code-await-merge  merged       cleanup\n"
    "  code-await-merge  changes      write-code\n\n"
    "hooks:\n"
    "  pr_merge  spec-await-merge  spec-merged\n"
    "  pr_merge  code-await-merge  merged\n"
    "  pr_close  spec-await-merge  abandoned\n"
    "  pr_close  code-await-merge  abandoned\n"
)


_LOOPING = (
    "entry: plan-next\n\n"
    "requires: brief repo\n\n"
    "phase:\n"
    "  plan-next         plan\n"
    "  write-code        code\n"
    "  code-open-pr      code\n"
    "  code-await-merge  code\n"
    "  cleanup           code\n\n"
    "nodes:\n"
    "  plan-next         planner\n"
    "  write-code        coder\n"
    "  code-await-merge  await-merge\n"
    "  cleanup           cleanup\n\n"
    "edges:\n"
    "  plan-next         item-selected  write-code\n"
    "  write-code        done           code-open-pr\n"
    "  code-await-merge  merged         cleanup\n"
    "  code-await-merge  changes        write-code\n"
    "  cleanup           done           plan-next\n\n"
    "hooks:\n"
    "  pr_merge  code-await-merge  merged\n"
)




class TestMonitorPrsMergeIntoAHumanStage(unittest.TestCase):
    def _setup(self):
        fs = FakeFs(
            metas={
                "planner": {"model": "sonnet"},
                "coder": {"model": "sonnet"},
                "await-merge": {"step": "await-merge"},
                "cleanup": {"step": "cleanup"},
            },
            workflow={"looping": _LOOPING},
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)
        item = store.create_item("deliver the plan", "a description", workflow="looping", project="lightcycle")
        store.add_artifact(item, "repo", "lightcycle")
        url = "https://github.com/x/y/pull/77"
        plant_pr(store, item, url, "code")
        step = store.create_step(
            "code-await-merge: deliver the plan", step="code-await-merge",
            role="human", parent=item,
        )
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, FakeWorktrees(), flow_service, CompleteStepUseCase(store, flow_service), CheckContentPinUseCase(store, _gh)
        )
        return store, item, step, uc

    def test_merge_routes_to_the_human_cleanup_stage_and_leaves_the_item_open(self):
        store, item, step, uc = self._setup()

        uc.execute()

        self.assertEqual(store.get_node(step).state, "done")
        self.assertEqual(store.get_node(step).outcome, "merged")
        self.assertEqual(store.get_node(item).state, State.WAITING)
        created = [n for n in store.all_steps() if n.stage == "cleanup" and n.item == item]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].role, "human")




class TestMonitorPrsSpecMergeContinuesToCode(unittest.TestCase):
    def _setup(self):
        fs = FakeFs(
            metas={
                "coder": {"model": "sonnet", "accepts": {"spec": "required"}},
                "await-merge": {"step": "await-merge"},
            },
            workflow={"spec-driven": _SPEC_DRIVEN},
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)
        spec_item = store.create_item("LC-59: phase c1", "a description", workflow="spec-driven", project="lightcycle")
        store.add_artifact(spec_item, "repo", "lightcycle")
        store.add_artifact(spec_item, "spec", "lightcycle/LC-59-phase-c1.md")
        store.add_artifact(spec_item, "branch", "spec/LC-59-phase-c1", label="spec")
        spec_url = "https://github.com/x/y/pull/101"
        plant_pr(store, spec_item, spec_url, "spec")
        store.create_step(
            "spec-await-merge: LC-59", step="spec-await-merge", role="human", parent=spec_item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={spec_url})
        complete = CompleteStepUseCase(store, flow_service)
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, complete, CheckContentPinUseCase(store, github)
        )
        return store, spec_item, uc, spec_url, worktrees, github

    def test_spec_merge_advances_the_same_item_to_write_code(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()

        result = uc.execute()

        self.assertEqual(result.merged, [spec_item])
        node = store.get_node(spec_item)
        self.assertEqual(node.id, spec_item)
        self.assertEqual(node.workflow, "spec-driven")
        self.assertEqual(node.state, State.QUEUED)
        all_items = [n for n in store.all_nodes() if n.type == "item"]
        self.assertEqual([n.id for n in all_items], [spec_item])
        steps = [s for s in store.children(spec_item) if s.state != "done"]
        self.assertEqual([s.stage for s in steps], ["write-code"])

    def test_crossing_the_phase_boundary_releases_only_the_spec_run(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()

        uc.execute()

        self.assertEqual(worktrees.released, ["%s.p1.spec" % spec_item])
        self.assertEqual(worktrees.removed, [])
        self.assertNotEqual(store.get_node(spec_item).state, "done")

    def test_running_twice_does_not_re_advance(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()
        uc.execute()
        first_run_steps = {s.id for s in store.children(spec_item)}

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual({s.id for s in store.children(spec_item)}, first_run_steps)

    def test_phase_filtered_pr_lookup_ignores_the_merged_spec_pr_once_a_code_pr_is_open(self):
        store, spec_item, uc, spec_url, worktrees, github = self._setup()
        uc.execute()

        code_url = "https://github.com/x/y/pull/202"
        plant_pr(store, spec_item, code_url, "code")

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(spec_item).state, State.QUEUED)


_SAME_REPO_TWO_PHASE = (
    "entry: feature-writer\n\n"
    "requires: brief repo\n\n"
    "phase:\n"
    "  feature-writer       feature\n"
    "  feature-await-merge  feature\n"
    "  write-code           code\n"
    "  code-await-merge     code\n\n"
    "nodes:\n"
    "  write-code           coder\n"
    "  feature-await-merge  await-merge\n"
    "  code-await-merge     await-merge\n\n"
    "edges:\n"
    "  feature-await-merge  feature-merged  write-code\n"
    "  feature-await-merge  changes         feature-writer\n"
    "  write-code           done            code-await-merge\n"
    "  code-await-merge     merged          cleanup\n\n"
    "hooks:\n"
    "  pr_merge  feature-await-merge  feature-merged\n"
    "  pr_merge  code-await-merge     merged\n"
    "  pr_close  feature-await-merge  abandoned\n"
    "  pr_close  code-await-merge     abandoned\n"
)




class TestMonitorPrsPhaseBoundarySameRepo(unittest.TestCase):
    def test_crossing_a_phase_boundary_removes_the_worktree_even_within_one_repo(self):
        fs = FakeFs(
            metas={
                "coder": {"model": "sonnet"},
                "await-merge": {"step": "await-merge"},
            },
            workflow={"bdd": _SAME_REPO_TWO_PHASE},
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)
        item = store.create_item("LC-7: login", "a description", workflow="bdd", project="app")
        store.add_artifact(item, "repo", "app")
        store.add_artifact(item, "branch", "feat/LC-7-feature-login", label="feature")
        url = "https://github.com/x/y/pull/7"
        plant_pr(store, item, url, "feature")
        store.create_step(
            "feature-await-merge: LC-7", step="feature-await-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, flow_service)
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, flow_service, complete, CheckContentPinUseCase(store, _gh)
        )

        uc.execute()

        self.assertEqual(worktrees.released, ["%s.p1.feature" % item])
        self.assertEqual(worktrees.removed, [])




class TestMonitorPrsMerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("my feature", "a description")
        plant_pr(store, item, pr_url)
        step = store.create_step(
            "ready-merge: my feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(flow or _FLOW), None, CheckContentPinUseCase(store, github)
        )
        return store, item, step, worktrees, uc

    def test_merged_pr_closes_story_and_children(self):
        url = "https://github.com/x/y/pull/1"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).disposition, "completed")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)

    def test_merged_story_closes_with_declared_merge_reason(self):
        url = "https://github.com/x/y/pull/2"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        uc.execute()

        self.assertEqual(store.get_node(item).outcome, "merged")
        self.assertEqual(store.get_node(item).disposition, "completed")

    def test_open_pr_does_not_close_story(self):
        url = "https://github.com/x/y/pull/3"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).state, State.WAITING)
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(worktrees.removed, [])

    def test_is_merged_failure_does_not_close_story(self):
        url = "https://github.com/x/y/pull/44"
        store, item, step, worktrees, uc = self._setup(
            url, FakeGitHub(merged_prs={url}, failing_calls={"is_merged"})
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(item).state, State.WAITING)
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(worktrees.removed, [])

    def test_already_closed_story_is_skipped(self):
        url = "https://github.com/x/y/pull/4"
        store = FakeStore()
        item = store.create_item("done feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(
            "ready-merge: done feature", step="ready-merge", role="human", parent=item
        )
        store.complete_node(step, "merged")
        store.complete_node(item, "merged")
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_merged_pr_closes_story_whose_live_task_is_upstream_of_ready_merge(self):
        url = "https://github.com/x/y/pull/40"
        store = FakeStore()
        item = store.create_item("upstream feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(
            "build: upstream feature", step="build", role="agent", parent=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).outcome, "merged")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)

    def test_merged_pr_closes_story_whose_live_task_regressed_to_review(self):
        url = "https://github.com/x/y/pull/41"
        store = FakeStore()
        item = store.create_item("regressed feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(
            "review: regressed feature", step="review", role="agent", parent=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).state, "done")

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        item = store.create_item("no-pr feature", "a description")
        store.create_step(
            "ready-merge: no-pr feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, github)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        create_owned_step(store, "ready-merge: orphan", step="ready-merge", role="human")
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={"x"})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_arbitrary_step_and_outcome_names_monitored_via_merge(self):
        arbitrary_flow = flow_from_metas(
            {
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"shipped": "done-step"},
                    "on_pr_merge": "shipped",
                }
            },
            disposition={"shipped": "completed"},
        )
        url = "https://github.com/x/y/pull/99"
        store = FakeStore()
        item = store.create_item("ship it", "a description")
        plant_pr(store, item, url)
        store.create_step("await-ship: ship it", step="await-ship", role="human", parent=item)
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(arbitrary_flow), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).outcome, "shipped")
        self.assertEqual(store.get_node(item).disposition, "completed")
        self.assertIn(item, worktrees.removed)




class TestMonitorPrsClosedUnmerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("abandoned feature", "a description")
        plant_pr(store, item, pr_url)
        step = store.create_step(
            "ready-merge: abandoned feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(flow or _FLOW), None, CheckContentPinUseCase(store, github)
        )
        return store, item, step, worktrees, uc

    def test_closed_unmerged_pr_closes_story(self):
        url = "https://github.com/x/y/pull/10"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).disposition, "aborted")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)

    def test_closed_unmerged_story_closes_with_declared_outcome(self):
        url = "https://github.com/x/y/pull/11"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        uc.execute()

        self.assertEqual(store.get_node(item).outcome, "abandoned")
        self.assertEqual(store.get_node(item).disposition, "aborted")

    def test_open_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/12"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub())

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).state, State.WAITING)
        self.assertEqual(worktrees.removed, [])

    def test_is_closed_unmerged_failure_does_not_close_story(self):
        url = "https://github.com/x/y/pull/45"
        store, item, step, worktrees, uc = self._setup(
            url, FakeGitHub(closed_prs={url}, failing_calls={"is_closed_unmerged"})
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).state, State.WAITING)
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(worktrees.removed, [])

    def test_merged_pr_does_not_take_abandon_path(self):
        url = "https://github.com/x/y/pull/13"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(merged_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(result.merged, [item])

    def test_arbitrary_close_outcome_name_is_used(self):
        arbitrary_flow = flow_from_metas(
            {
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"shipped": "done-step", "cancelled": "done-step"},
                    "on_pr_merge": "shipped",
                    "on_pr_close": "cancelled",
                }
            },
            disposition={"shipped": "completed", "cancelled": "aborted"},
        )
        url = "https://github.com/x/y/pull/20"
        store = FakeStore()
        item = store.create_item("cancelled work", "a description")
        plant_pr(store, item, url)
        store.create_step(
            "await-ship: cancelled work", step="await-ship", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(arbitrary_flow), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).outcome, "cancelled")
        self.assertEqual(store.get_node(item).disposition, "aborted")
        self.assertIn(item, worktrees.removed)

    def test_step_without_on_pr_close_not_abandoned_on_close(self):
        url = "https://github.com/x/y/pull/21"
        store, item, step, worktrees, uc = self._setup(
            url, FakeGitHub(closed_prs={url}), flow=_MERGE_ONLY_FLOW
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).state, State.WAITING)

    def test_closed_unmerged_pr_advances_to_a_declared_gate_instead_of_closing(self):
        url = "https://github.com/x/y/pull/23"
        store = FakeStore()
        item = store.create_item("gated feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(
            "ready-merge: gated feature", step="ready-merge", role="human", parent=item
        )
        worktrees = FakeWorktrees()
        flow_adapter = _FlowAdapter(_CLOSE_ROUTES_TO_HUMAN_GATE_FLOW)
        complete = CompleteStepUseCase(store, flow_adapter)
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, flow_adapter, complete, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).state, State.WAITING)
        self.assertEqual(store.get_node(step).state, "done")
        live_steps = [s for s in store.children(item) if s.state != "done"]
        self.assertEqual([s.stage for s in live_steps], ["confirm-abandon"])
        self.assertEqual(worktrees.removed, [])

    def test_closed_unmerged_pr_closes_story_whose_live_task_is_at_watch_pr(self):
        url = "https://github.com/x/y/pull/22"
        store = FakeStore()
        item = store.create_item("watched feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(
            "watch-pr: watched feature", step="watch-pr", role="agent", parent=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh)
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)




class TestLatestStepOrdering(unittest.TestCase):
    def test_mixed_utc_offsets_sort_chronologically_not_as_raw_strings(self):
        store = FakeStore()
        item = store.create_item("it", "a description")
        earliest = store.create_step("earliest", step="build", role="agent", parent=item)
        store._records[earliest]["created_at"] = "2026-01-01T10:00:00+00:00"
        true_latest = store.create_step("true-latest", step="build", role="agent", parent=item)
        store._records[true_latest]["created_at"] = "2026-01-01T05:00:00-12:00"
        greatest_raw_string = store.create_step(
            "greatest-raw-string", step="build", role="agent", parent=item
        )
        store._records[greatest_raw_string]["created_at"] = "2026-01-01T15:00:00+00:00"

        result = latest_step(store, item)

        self.assertEqual(result.id, true_latest)


if __name__ == "__main__":
    unittest.main()


