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

    def unpinned_workflow(self, node):
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

    def escalated_transition(self, transition, outcome, history, name=None, project=None):
        return self._flow.escalated_transition(transition, outcome, history, lambda key: None)

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
    disposition={"merged": "completed", "abandoned": "abandoned"},
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


_ROUTES_TO_STAGE_FLOW = flow_from_metas(
    {
        "reviewer": {
            "step": "ready-merge",
            "routes": {"merged": "cleanup", "abandoned": "build"},
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
        },
        "cleanup": {"step": "cleanup"},
        "build": {"step": "build"},
    }
)


class FakeWorktrees:
    def teardown_refusals(self, item, merged_prs=frozenset()):
        return []

    def pass_release_refusals(self, item, runs):
        return []

    def phase_release_refusals(self, run):
        return []

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
            store, _gh, FakeWorktrees(), _TripwireFlow(), None, CheckContentPinUseCase(store, _gh, _TripwireFlow(), trusted_authors=lambda: frozenset({"review-code"}))
        )
        result = uc.execute()
        self.assertEqual(result.merged, [])
        self.assertEqual(result.abandoned, [])




class TestMonitorPrsSkipsItemsWithNoOpenStep(unittest.TestCase):
    def _backlogged_with_pr(self, url):
        store = FakeStore()
        item = store.create_item("put back", "a description")
        plant_pr(store, item, url)
        return store, item

    def _use_case(self, store, github):
        return ResolveMergedPrsUseCase(
            store, github, FakeWorktrees(), _FlowAdapter(_FLOW), None,
            CheckContentPinUseCase(store, github, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"})),
        )

    def test_backlogged_item_whose_run_carries_a_merged_pr_is_not_closed(self):
        url = "https://github.com/x/y/pull/61"
        store, item = self._backlogged_with_pr(url)

        result = self._use_case(store, FakeGitHub(merged_prs={url})).execute()

        self.assertEqual(result.merged, [])
        self.assertNotEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).state, State.BACKLOGGED)

    def test_backlogged_item_whose_run_carries_a_closed_pr_is_not_closed(self):
        url = "https://github.com/x/y/pull/62"
        store, item = self._backlogged_with_pr(url)

        result = self._use_case(store, FakeGitHub(closed_prs={url})).execute()

        self.assertEqual(result.abandoned, [])
        self.assertEqual(store.get_node(item).state, State.BACKLOGGED)

    def test_live_await_merge_step_still_closes_the_item_on_merge(self):
        url = "https://github.com/x/y/pull/63"
        store, item = self._backlogged_with_pr(url)
        store.create_step(stage="ready-merge", role="human", item=item)

        result = self._use_case(store, FakeGitHub(merged_prs={url})).execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, "done")


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
                    "  abandoned  abandoned\n"
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
                    "  abandoned    abandoned\n"
                ),
            },
        )
        store = FakeStore()
        flow_service = FlowService(fs, store)

        code_item = store.create_item("code feature", "a description", workflow="standard")
        code_url = "https://github.com/x/y/pull/100"
        plant_pr(store, code_item, code_url)
        store.create_step(stage="await-merge", role="human", item=code_item
        )

        spec_item = store.create_item("a spec", "a description", workflow="spec")
        spec_url = "https://github.com/x/y/pull/101"
        plant_pr(store, spec_item, spec_url)
        store.create_step(stage="await-merge", role="human", item=spec_item
        )

        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={code_url, spec_url})
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, None, CheckContentPinUseCase(store, github, flow_service, trusted_authors=lambda: frozenset({"review-code"}))
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
        step = store.create_step(stage="code-await-merge",
            role="human", item=item)
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, FakeWorktrees(), flow_service, CompleteStepUseCase(store, flow_service), CheckContentPinUseCase(store, _gh, flow_service, trusted_authors=lambda: frozenset({"review-code"}))
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




class _RaisingComplete:
    def execute(self, inp):
        raise RuntimeError("completion failed")


class TestMonitorPrsResolvePairIsOneTransaction(unittest.TestCase):
    def _setup(self, github_kwargs):
        store = FakeStore()
        item = store.create_item("deliver", "a description")
        url = "https://github.com/x/y/pull/71"
        rid = plant_pr(store, item, url)
        step = store.create_step(stage="ready-merge", role="human", item=item)
        worktrees = FakeWorktrees()
        github = FakeGitHub(**github_kwargs(url))
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(_ROUTES_TO_STAGE_FLOW), _RaisingComplete(),
            CheckContentPinUseCase(store, github, _FlowAdapter(_ROUTES_TO_STAGE_FLOW), trusted_authors=lambda: frozenset({"review-code"})),
        )
        return store, item, rid, step, worktrees, uc

    def test_failed_completion_on_merge_leaves_the_run_open_for_the_next_tick(self):
        store, item, rid, step, worktrees, uc = self._setup(lambda url: {"merged_prs": {url}})

        with self.assertRaises(RuntimeError):
            uc.execute()

        self.assertEqual([r.id for r in store.open_runs_of(item)], [rid])
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(getattr(worktrees, "released", []), [])

    def test_failed_completion_on_close_leaves_the_run_open_for_the_next_tick(self):
        store, item, rid, step, worktrees, uc = self._setup(
            lambda url: {"closed_prs": {url}}
        )

        with self.assertRaises(RuntimeError):
            uc.execute()

        self.assertEqual([r.id for r in store.open_runs_of(item)], [rid])
        self.assertNotEqual(store.get_node(step).state, "done")


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
        store.create_step(stage="spec-await-merge", role="human", item=spec_item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={spec_url})
        complete = CompleteStepUseCase(store, flow_service)
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, flow_service, complete, CheckContentPinUseCase(store, github, flow_service, trusted_authors=lambda: frozenset({"review-code"}))
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
        store.create_step(stage="feature-await-merge", role="human", item=item
        )
        worktrees = FakeWorktrees()
        complete = CompleteStepUseCase(store, flow_service)
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, flow_service, complete, CheckContentPinUseCase(store, _gh, flow_service, trusted_authors=lambda: frozenset({"review-code"}))
        )

        uc.execute()

        self.assertEqual(worktrees.released, ["%s.p1.feature" % item])
        self.assertEqual(worktrees.removed, [])




class TestMonitorPrsMerged(unittest.TestCase):
    def _setup(self, pr_url, github, flow=None):
        store = FakeStore()
        item = store.create_item("my feature", "a description")
        plant_pr(store, item, pr_url)
        step = store.create_step(stage="ready-merge", role="human", item=item
        )
        worktrees = FakeWorktrees()
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(flow or _FLOW), None, CheckContentPinUseCase(store, github, _FlowAdapter(flow or _FLOW), trusted_authors=lambda: frozenset({"review-code"}))
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
        step = store.create_step(stage="ready-merge", role="human", item=item
        )
        store.complete_node(step, "merged")
        store.complete_node(item, "merged")
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_merged_pr_closes_story_whose_live_task_is_upstream_of_ready_merge(self):
        url = "https://github.com/x/y/pull/40"
        store = FakeStore()
        item = store.create_item("upstream feature", "a description")
        plant_pr(store, item, url)
        step = store.create_step(stage="build", role="agent", item=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
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
        step = store.create_step(stage="review", role="agent", item=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
        )

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).state, "done")

    def test_task_without_pr_artifact_is_skipped(self):
        store = FakeStore()
        item = store.create_item("no-pr feature", "a description")
        store.create_step(stage="ready-merge", role="human", item=item
        )
        worktrees = FakeWorktrees()
        github = FakeGitHub(merged_prs={"anything"})
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, github, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
        )

        result = uc.execute()

        self.assertEqual(result.merged, [])

    def test_task_without_parent_is_skipped(self):
        store = FakeStore()
        create_owned_step(store, "ready-merge: orphan", stage="ready-merge", role="human")
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={"x"})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
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
        store.create_step(stage="await-ship", role="human", item=item)
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(arbitrary_flow), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(arbitrary_flow), trusted_authors=lambda: frozenset({"review-code"}))
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
        step = store.create_step(stage="ready-merge", role="human", item=item
        )
        worktrees = FakeWorktrees()
        uc = ResolveMergedPrsUseCase(
            store, github, worktrees, _FlowAdapter(flow or _FLOW), None, CheckContentPinUseCase(store, github, _FlowAdapter(flow or _FLOW), trusted_authors=lambda: frozenset({"review-code"}))
        )
        return store, item, step, worktrees, uc

    def test_closed_unmerged_pr_closes_story(self):
        url = "https://github.com/x/y/pull/10"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(result.merged, [])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(item).disposition, "abandoned")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)

    def test_closed_unmerged_story_closes_with_declared_outcome(self):
        url = "https://github.com/x/y/pull/11"
        store, item, step, worktrees, uc = self._setup(url, FakeGitHub(closed_prs={url}))

        uc.execute()

        self.assertEqual(store.get_node(item).outcome, "abandoned")
        self.assertEqual(store.get_node(item).disposition, "abandoned")

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
            disposition={"shipped": "completed", "cancelled": "abandoned"},
        )
        url = "https://github.com/x/y/pull/20"
        store = FakeStore()
        item = store.create_item("cancelled work", "a description")
        plant_pr(store, item, url)
        store.create_step(stage="await-ship", role="human", item=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(arbitrary_flow), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(arbitrary_flow), trusted_authors=lambda: frozenset({"review-code"}))
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).outcome, "cancelled")
        self.assertEqual(store.get_node(item).disposition, "abandoned")
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
        step = store.create_step(stage="ready-merge", role="human", item=item
        )
        worktrees = FakeWorktrees()
        flow_adapter = _FlowAdapter(_CLOSE_ROUTES_TO_HUMAN_GATE_FLOW)
        complete = CompleteStepUseCase(store, flow_adapter)
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, flow_adapter, complete, CheckContentPinUseCase(store, _gh, flow_adapter, trusted_authors=lambda: frozenset({"review-code"}))
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
        step = store.create_step(stage="watch-pr", role="agent", item=item
        )
        worktrees = FakeWorktrees()
        _gh = FakeGitHub(closed_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, worktrees, _FlowAdapter(_FLOW), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(_FLOW), trusted_authors=lambda: frozenset({"review-code"}))
        )

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).state, "done")
        self.assertEqual(store.get_node(step).state, "done")
        self.assertIn(item, worktrees.removed)




class TestUndeclaredDispositionParksTheMergeStage(unittest.TestCase):
    def test_a_merge_outcome_without_a_disposition_parks_the_merge_step_not_an_earlier_open_step(self):
        flow = flow_from_metas(
            {
                "spec-fb": {"step": "spec-feedback", "routes": {"done": "await-ship"}},
                "gatekeeper": {
                    "step": "await-ship",
                    "routes": {"shipped": "done-step"},
                    "on_pr_merge": "shipped",
                },
            },
        )
        url = "https://github.com/x/y/pull/98"
        store = FakeStore()
        item = store.create_item("ship it", "a description")
        plant_pr(store, item, url)
        other = store.create_step(stage="spec-feedback", role="agent", item=item)
        merge_step = store.create_step(stage="await-ship", role="human", item=item)
        _gh = FakeGitHub(merged_prs={url})
        uc = ResolveMergedPrsUseCase(
            store, _gh, FakeWorktrees(), _FlowAdapter(flow), None, CheckContentPinUseCase(store, _gh, _FlowAdapter(flow), trusted_authors=lambda: frozenset({"review-code"}))
        )

        uc.execute()

        self.assertIn("does not declare", store.get_node(merge_step).park.reason)
        self.assertIsNone(store.get_node(other).park.reason)


class TestLatestStepOrdering(unittest.TestCase):
    def test_mixed_utc_offsets_sort_chronologically_not_as_raw_strings(self):
        store = FakeStore()
        item = store.create_item("it", "a description")
        earliest = store.create_step(stage="build", role="agent", item=item)
        store._records[earliest]["created_at"] = "2026-01-01T10:00:00+00:00"
        true_latest = store.create_step(stage="build", role="agent", item=item)
        store._records[true_latest]["created_at"] = "2026-01-01T05:00:00-12:00"
        greatest_raw_string = store.create_step(stage="build", role="agent", item=item
        )
        store._records[greatest_raw_string]["created_at"] = "2026-01-01T15:00:00+00:00"

        result = latest_step(store, item)

        self.assertEqual(result.id, true_latest)


if __name__ == "__main__":
    unittest.main()




_TWO_GATES_ONE_PHASE = (
    "entry: spec-writer\n\n"
    "requires: brief repo\n\n"
    "phase:\n"
    "  spec-writer         spec\n"
    "  spec-await-merge    spec\n"
    "  nochange-await-merge spec\n"
    "  write-code          code\n\n"
    "nodes:\n"
    "  spec-await-merge     await-merge\n"
    "  nochange-await-merge await-merge\n"
    "  write-code           coder\n"
    "  spec-writer          coder\n\n"
    "edges:\n"
    "  spec-await-merge     spec-merged  write-code\n"
    "  nochange-await-merge no-change-merged  end\n"
    "  spec-await-merge     abandoned    spec-writer\n\n"
    "hooks:\n"
    "  pr_merge  nochange-await-merge  no-change-merged\n"
    "  pr_merge  spec-await-merge      spec-merged\n"
    "  pr_close  nochange-await-merge  no-change-abandoned\n"
    "  pr_close  spec-await-merge      abandoned\n\n"
    "disposition:\n"
    "  no-change-merged     completed\n"
    "  no-change-abandoned  abandoned\n"
)


class TestSharedPhaseGatesResolveOnlyTheGateTheItemIsAt(unittest.TestCase):
    def _setup(self, at, github_kwargs, github=None):
        from lightcycle.domain.flow import Flow
        from lightcycle.domain.flow.graph import parse_graph

        metas = {"await-merge": {"step": "await-merge"}, "coder": {"model": "sonnet"}}
        flow = Flow.from_graph(parse_graph(_TWO_GATES_ONE_PHASE), metas)
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        url = "https://github.com/x/y/pull/9"
        plant_pr(store, item, url, "spec")
        step = store.create_step(stage=at, role="human", item=item)
        gh = github(url) if github else FakeGitHub(**github_kwargs(url))
        adapter = _FlowAdapter(flow)
        uc = ResolveMergedPrsUseCase(
            store, gh, FakeWorktrees(), adapter, CompleteStepUseCase(store, adapter),
            CheckContentPinUseCase(store, gh, adapter, trusted_authors=lambda: frozenset({"review-code"})),
        )
        return store, item, step, uc

    def test_a_merge_read_once_is_not_lost_to_the_gate_checked_first(self):
        from lightcycle.adapters.simulate import ScriptedGitHub

        def scripted(url):
            gh = ScriptedGitHub()
            gh.script_merge(url)
            return gh

        store, item, step, uc = self._setup("spec-await-merge", None, github=scripted)

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).outcome, "spec-merged")

    def test_merge_at_the_edge_gate_advances_and_does_not_close_through_the_terminal_gate(self):
        store, item, step, uc = self._setup("spec-await-merge", lambda u: {"merged_prs": {u}})

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).outcome, "spec-merged")
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertEqual(
            [s.stage for s in store.children(item) if s.state != "done"], ["write-code"]
        )

    def test_merge_at_the_terminal_gate_still_closes_the_item_with_its_disposition(self):
        store, item, step, uc = self._setup("nochange-await-merge", lambda u: {"merged_prs": {u}})

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(item).state, State.DONE)

    def test_close_at_the_edge_gate_does_not_close_through_the_terminal_gate(self):
        store, item, step, uc = self._setup("spec-await-merge", lambda u: {"closed_prs": {u}})

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(step).outcome, "abandoned")
        self.assertNotEqual(store.get_node(item).state, State.DONE)

    def test_close_at_the_terminal_gate_still_closes_the_item_with_its_disposition(self):
        store, item, step, uc = self._setup("nochange-await-merge", lambda u: {"closed_prs": {u}})

        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
        self.assertEqual(store.get_node(item).state, State.DONE)


class _RefusingWorktrees(FakeWorktrees):
    def __init__(self):
        super().__init__()
        self.merged_prs_seen = []

    def teardown_refusals(self, item, merged_prs=frozenset()):
        self.merged_prs_seen.append(merged_prs)
        return ["worktree /w has uncommitted paths: a.py"]

    def pass_release_refusals(self, item, runs):
        return []

    def phase_release_refusals(self, run):
        return []


class TestTeardownRefusalSkipsTheItemForTheTick(unittest.TestCase):
    def test_two_ticks_leave_the_item_open_with_one_park_note(self):
        from lightcycle.domain.flow import Flow
        from lightcycle.domain.flow.graph import parse_graph

        metas = {"await-merge": {"step": "await-merge"}, "coder": {"model": "sonnet"}}
        flow = Flow.from_graph(parse_graph(_TWO_GATES_ONE_PHASE), metas)
        store = FakeStore()
        item = store.create_item("spec item", "a description")
        url = "https://github.com/x/y/pull/9"
        plant_pr(store, item, url, "spec")
        step = store.create_step(stage="nochange-await-merge", role="human", item=item)
        gh = FakeGitHub(merged_prs={url})
        adapter = _FlowAdapter(flow)
        worktrees = _RefusingWorktrees()
        uc = ResolveMergedPrsUseCase(
            store, gh, worktrees, adapter, CompleteStepUseCase(store, adapter),
            CheckContentPinUseCase(store, gh, adapter, trusted_authors=lambda: frozenset({"review-code"})),
        )

        first = uc.execute()
        second = uc.execute()

        self.assertEqual(first.merged, [])
        self.assertEqual(second.merged, [])
        self.assertNotEqual(store.get_node(item).state, State.DONE)
        self.assertEqual((store.get_node(step).notes or "").count("BLOCKED:"), 1)
        self.assertEqual(worktrees.merged_prs_seen[0], frozenset({url}))


class _GuardCfg:
    def worktree_retries(self):
        return 0

    def worktree_retry_sleep(self):
        return 0

    def branch_prefix(self):
        return "feat"

    def projects_root(self):
        return "/projects"

    def engine_root(self):
        return "lightcycle"


class TestPhaseReleaseGuard(unittest.TestCase):
    REPO = "/elsewhere/app"
    BRANCH = "feat/app-x"
    URL = "https://github.com/x/y/pull/21"

    def _setup(self, github, flow=None, **git_kwargs):
        from lightcycle.application.services.worktree import WorktreeService
        from tests.support.fake_git import FakeGit

        store = FakeStore()
        item = store.create_item("my feature", "a description")
        store.add_artifact(item, "repo", self.REPO)
        rid = plant_pr(store, item, self.URL, branch=self.BRANCH)
        step = store.create_step(stage="ready-merge", role="human", item=item)
        git = FakeGit(branches={(self.REPO, self.BRANCH)}, ref="origin/main", **git_kwargs)
        svc = WorktreeService(store, git, fs=None, config=_GuardCfg())
        adapter = _FlowAdapter(flow or _FLOW)
        uc = ResolveMergedPrsUseCase(
            store, github, svc, adapter, CompleteStepUseCase(store, adapter),
            CheckContentPinUseCase(store, github, adapter, trusted_authors=lambda: frozenset({"review-code"})),
        )
        path = svc.path_for_run(store.get_run(rid))
        return store, item, step, rid, git, uc, path

    @staticmethod
    def _removed(git):
        return [c for c in git.calls if c[0] in ("remove_worktree", "delete_branch")]

    def test_dirty_merged_phase_worktree_parks_the_gate_and_releases_nothing(self):
        store, item, step, rid, git, uc, path = self._setup(FakeGitHub(merged_prs={self.URL}))
        git._registered = {path}
        git._uncommitted = {path: ["a.py", "b.py"]}

        result = uc.execute()

        self.assertEqual(result.merged, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertTrue(store.get_run(rid).is_open)
        self.assertEqual(self._removed(git), [])
        self.assertIn("a.py, b.py", store.get_node(step).park.reason)

    def test_two_ticks_over_a_dirty_tree_leave_one_park_note_then_a_clean_tick_completes(self):
        store, item, step, rid, git, uc, path = self._setup(FakeGitHub(merged_prs={self.URL}))
        git._registered = {path}
        git._uncommitted = {path: ["a.py"]}

        uc.execute()
        uc.execute()

        self.assertEqual((store.get_node(step).notes or "").count("BLOCKED:"), 1)

        git._uncommitted = {}
        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).state, "done")

    def test_clean_worktree_proceeds_even_with_commits_beyond_the_base(self):
        store, item, step, rid, git, uc, path = self._setup(
            FakeGitHub(merged_prs={self.URL}), beyond={(self.REPO, self.BRANCH): ["a1"]}
        )
        git._registered = {path}

        result = uc.execute()

        self.assertEqual(result.merged, [item])
        self.assertEqual(store.get_node(step).state, "done")

    def test_abandoned_close_gets_the_same_dirty_only_check(self):
        flow_with_abandon = flow_from_metas(
            {
                "reviewer": {
                    "step": "ready-merge",
                    "routes": {"merged": "cleanup", "abandoned": "build"},
                    "on_pr_merge": "merged",
                    "on_pr_close": "abandoned",
                },
                "cleanup": {"step": "cleanup"},
                "build": {"step": "build"},
            }
        )
        url = self.URL
        store, item, step, rid, git, uc, path = self._setup(
            FakeGitHub(closed_prs={url}), flow=flow_with_abandon
        )
        git._registered = {path}
        git._uncommitted = {path: ["a.py"]}

        result = uc.execute()

        self.assertEqual(result.abandoned, [])
        self.assertNotEqual(store.get_node(step).state, "done")
        self.assertEqual(self._removed(git), [])

        git._uncommitted = {}
        result = uc.execute()

        self.assertEqual(result.abandoned, [item])
