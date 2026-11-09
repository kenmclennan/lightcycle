import json
import tempfile
import unittest
from unittest import mock

from lightcycle.adapters import spawner
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.doctor import DoctorInput, DoctorUseCase
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work import ShowNodeInput, ShowNodeUseCase
from lightcycle.application.work.link_artifact import LinkArtifactInput, LinkArtifactUseCase
from lightcycle.application.work.stack_layers import StackLayers
from lightcycle.config import Config
from lightcycle.domain.health.gh_tooling import (
    GhTooling,
    gh_tooling_problems,
    parse_extensions,
    parse_gh_version,
)
from lightcycle.domain.runs import PhaseRun
from lightcycle.ports.github import StackLayer
from tests.support.fake_fs import FakeFs
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_doctor import (
    _ALL_KEYS,
    FakeConfigReloadStatus,
    FakeGit,
    FakeGithubBudget,
    FakeGuidanceSyncStatus,
    FakeLock,
    FakeWorkflowBundle,
    FakeWorkflowSource,
    _cfg,
    _Worktrees,
)
from tests.support.fake_machine import FakeMachine

_STACK = "https://github.com/acme/widget/stack/3"
_LAYERS = (
    StackLayer(4, "https://github.com/acme/widget/pull/4", "a", "main", "s1", "merged"),
    StackLayer(5, "https://github.com/acme/widget/pull/5", "b", "main", "s2", "open"),
)


class TestPhaseRunStack(unittest.TestCase):
    def test_a_run_has_no_stack_by_default(self):
        self.assertIsNone(PhaseRun("r", "LC-1", "LC-1.p1").stack)
        self.assertIsNone(PhaseRun("r", "LC-1", "LC-1.p1").as_dict()["stack"])


class TestAttachStack(unittest.TestCase):
    def test_attach_stack_lands_on_the_open_run(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "code")
        LinkArtifactUseCase(s, FakeGitHub(), flow=None).execute(LinkArtifactInput(item=sid, atype="stack", value=_STACK))
        self.assertEqual(s.get_run(rid).stack, _STACK)
        self.assertIsNone(s.get_run(rid).pr)

    def test_attach_stack_with_no_open_run_refuses(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        with self.assertRaisesRegex(UseCaseError, "no open phase run"):
            LinkArtifactUseCase(s, FakeGitHub(), flow=None).execute(LinkArtifactInput(item=sid, atype="stack", value=_STACK))

    def test_attach_stack_to_a_step_id_refuses(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        s.open_run(sid, s.open_pass(sid), "code")
        step = s.create_step(stage="code-open-pr", item=sid)
        with self.assertRaisesRegex(UseCaseError, "is a step"):
            LinkArtifactUseCase(s, FakeGitHub(), flow=None).execute(LinkArtifactInput(item=step, atype="stack", value=_STACK))

    def test_attach_stack_records_the_layers_seen(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "code")
        github = FakeGitHub()
        github.script_stack(_STACK, _LAYERS)
        LinkArtifactUseCase(s, github, flow=None).execute(LinkArtifactInput(item=sid, atype="stack", value=_STACK))
        self.assertEqual(
            [e["head_ref"] for e in json.loads(s.get_run(rid).stack_seen)], ["a", "b"]
        )

    def test_attach_stack_with_a_failing_read_leaves_the_record_empty(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "code")
        github = FakeGitHub(failing_calls={"stack_view"})
        github.script_stack(_STACK, _LAYERS)
        LinkArtifactUseCase(s, github, flow=None).execute(LinkArtifactInput(item=sid, atype="stack", value=_STACK))
        self.assertEqual(s.get_run(rid).stack, _STACK)
        self.assertIsNone(s.get_run(rid).stack_seen)

    def test_attach_pr_leaves_the_stack_alone(self):
        s = FakeStore()
        sid = s.create_item("st", "a description")
        rid = s.open_run(sid, s.open_pass(sid), "code")
        LinkArtifactUseCase(s, FakeGitHub(), flow=None).execute(LinkArtifactInput(item=sid, atype="stack", value=_STACK))
        LinkArtifactUseCase(s, FakeGitHub(), flow=None).execute(LinkArtifactInput(item=sid, atype="pr", value="http://x/pull/9"))
        self.assertEqual(s.get_run(rid).stack, _STACK)
        self.assertEqual(s.get_run(rid).pr, "http://x/pull/9")


class TestStackOnTheReadSurface(unittest.TestCase):
    def _show(self, github, stack=_STACK):
        s = FakeStore()
        item = s.create_item("st", "a description", workflow="wf")
        rid = s.open_run(item, s.open_pass(item), "code")
        if stack:
            s.set_stack(rid, stack)
        step = s.create_step(stage="code-await-merge", role="human", item=item)
        flow = FlowService(FakeFs({"some-role": {"step": "code-await-merge", "phase": "code"}}), s)
        uc = ShowNodeUseCase(s, flow, StackLayers(github))
        return (
            uc.execute(ShowNodeInput(step=step)).as_dict(),
            uc.execute(ShowNodeInput(step=item)).as_dict(),
        )

    def test_an_item_shows_the_stack_and_its_layers_in_order(self):
        _, item_surface = self._show(FakeGitHub(stacks={_STACK: _LAYERS}))
        self.assertEqual(item_surface["stack"], _STACK)
        self.assertEqual([l["number"] for l in item_surface["stack_layers"]], [4, 5])
        self.assertEqual(item_surface["stack_layers"][0]["state"], "merged")
        self.assertNotIn("stack_error", item_surface)

    def test_a_failed_read_shows_the_error_and_no_layers(self):
        step_surface, item_surface = self._show(FakeGitHub(failing_calls=("stack_view",)))
        for surface in (step_surface, item_surface):
            self.assertEqual(surface["stack"], _STACK)
            self.assertNotIn("stack_layers", surface)
            self.assertEqual(surface["stack_error"], "stack read failed (exit 1): boom")

    def test_an_unstacked_run_shows_no_stack_keys_and_makes_no_read(self):
        github = FakeGitHub()
        step_surface, item_surface = self._show(github, stack=None)
        for surface in (step_surface, item_surface):
            for key in ("stack", "stack_layers", "stack_error"):
                self.assertNotIn(key, surface)
        self.assertEqual(github.calls, [])


class TestUpdateBehindSkipsStackedRuns(unittest.TestCase):
    def test_a_stacked_run_is_not_updated_but_an_unstacked_one_is(self):
        from tests.unit.test_update_behind_prs import _Harness as Harness, _behind, _pr

        github, stacked_url = _behind(1, head="aaa1111")
        h = Harness(github)
        item, step = h.gate(stacked_url)
        h.store.set_stack(h.store.current_run(item, None).id, _STACK)

        result = h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(result.updated, [])
        self.assertEqual(h.notes(step), "")

        other_url = _pr(2)
        github._behind.add(other_url)
        github._head_shas[other_url] = "bbb2222"
        other_item, other_step = h.gate(other_url, title="plain")

        result = h.uc.execute()

        self.assertEqual(github.update_calls, [(other_url, "bbb2222")])
        self.assertEqual(result.updated, [other_item])
        self.assertEqual(h.notes(step), "")


class TestGhToolingDomain(unittest.TestCase):
    def test_version_table(self):
        for text, expected in (
            ("gh version 2.103.3 (2026-01-01)\nhttps://x", (2, 103)),
            ("gh version 2.89.9", (2, 89)),
            ("gh version 2.90.0", (2, 90)),
            ("gh version 3.0.0", (3, 0)),
            ("", None),
            ("garbage", None),
            (None, None),
        ):
            self.assertEqual(parse_gh_version(text), expected, text)

    def test_the_version_gate_compares_integers_not_strings(self):
        ext = "gh stack\tgithub/gh-stack\tv0.3.0\n"
        for text, healthy in (
            ("gh version 2.103.3", True), ("gh version 2.89.9", False),
            ("gh version 2.90.0", True), ("gh version 3.0.0", True),
        ):
            problems = gh_tooling_problems(GhTooling(text, ext))
            self.assertEqual(problems == [], healthy, text)

    def test_old_gh_names_the_version_found(self):
        problems = gh_tooling_problems(GhTooling("gh version 2.89.9", "x\tgithub/gh-stack\tv1"))
        self.assertEqual(len(problems), 1)
        self.assertIn("2.89", problems[0].message)

    def test_extension_parse(self):
        self.assertEqual(parse_extensions("gh stack\tgithub/gh-stack\tv0.3.0"), ["github/gh-stack"])
        self.assertEqual(parse_extensions(""), [])
        self.assertEqual(parse_extensions(None), [])

    def test_missing_extension_names_the_fix(self):
        problems = gh_tooling_problems(GhTooling("gh version 2.103.3", ""))
        self.assertEqual(len(problems), 1)
        self.assertIn("gh extension install github/gh-stack", problems[0].fix)
        self.assertEqual(problems[0].category, "github")

    def test_unreadable_extension_list_is_one_problem(self):
        problems = gh_tooling_problems(GhTooling("gh version 2.103.3", None))
        self.assertEqual(len(problems), 1)
        self.assertIn("could not be read", problems[0].message)

    def test_gh_absent_is_one_problem_not_three(self):
        self.assertEqual(len(gh_tooling_problems(GhTooling(None, None))), 1)


class TestDoctorReportsGhTooling(unittest.TestCase):
    def _problems(self, machine):
        source = FakeWorkflowSource()
        source.add_bundle("acme", "sha1", 1, current=True)
        report = DoctorUseCase(
            FakeStore(), source, _cfg(**_ALL_KEYS), FakeWorkflowBundle(), FakeFs(), machine,
            _Worktrees(), FakeGit(), FakeGuidanceSyncStatus(), FakeConfigReloadStatus(),
            FakeLock(running=False), FakeGithubBudget(), lambda seconds: None,
        ).execute(DoctorInput())
        return report.problems["github"]

    def test_a_healthy_default_reports_nothing(self):
        self.assertEqual(self._problems(FakeMachine()), [])

    def test_a_missing_gh_stack_is_reported_in_the_github_section(self):
        problems = self._problems(FakeMachine(gh_tooling=GhTooling("gh version 2.103.3", "")))
        self.assertEqual(len(problems), 1)
        self.assertIn("gh extension install github/gh-stack", problems[0].fix)


class TestSpawnerSuppressesTheStackUpdateNotice(unittest.TestCase):
    def _env(self, environ):
        with tempfile.TemporaryDirectory() as root:
            config = Config(environ=dict(environ, LC_HOME=root, LC_MAX_AGENTS="3"))
            with mock.patch(
                "lightcycle.adapters.spawner.subprocess.Popen"
            ) as popen, mock.patch("lightcycle.adapters.spawner.capture_pid_started", return_value=1.0):
                popen.return_value.pid = 999
                spawner.spawn_worker(config, "agent")
        return popen.call_args.kwargs["env"]

    def test_the_default_path_sets_the_variable(self):
        self.assertEqual(self._env({})["GH_STACK_NO_UPDATE_NOTIFIER"], "1")

    def test_the_spawn_cmd_override_path_sets_it_too(self):
        self.assertEqual(
            self._env({"LC_SPAWN_CMD": "true"})["GH_STACK_NO_UPDATE_NOTIFIER"], "1")


class TestStackViewDoubles(unittest.TestCase):
    def test_fake_returns_the_scripted_tuple_and_fails_for_an_unscripted_url(self):
        from lightcycle.ports.github import ReadFailure
        fake = FakeGitHub(stacks={_STACK: _LAYERS})
        self.assertEqual(fake.stack_view(_STACK), _LAYERS)
        self.assertIsInstance(fake.stack_view("https://github.com/a/b/stack/9"), ReadFailure)

    def test_scripted_github_answers_from_its_fixture(self):
        from lightcycle.adapters.simulate import ScriptedGitHub
        from lightcycle.ports.github import ReadFailure
        sim = ScriptedGitHub()
        self.assertIsInstance(sim.stack_view(_STACK), ReadFailure)
        sim.script_stack(_STACK, _LAYERS)
        self.assertEqual(sim.stack_view(_STACK), _LAYERS)

    def test_a_pr_snapshot_has_no_stack_entry_yet(self):
        from lightcycle.application.pool.pr_snapshot import PrSnapshot
        from lightcycle.ports.github import NotYetRead
        self.assertIsInstance(PrSnapshot(FakeGitHub()).stack_view(_STACK), NotYetRead)
