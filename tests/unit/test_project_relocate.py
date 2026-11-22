import errno
import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.setup.project_registry import AddProjectInput, AddProjectUseCase
from lightcycle.application.setup.project_relocate import RelocateProjectUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore

HOME = "/home/u"
OLD = "/abs/old"
NEW = "/abs/new"


class _Config:
    def __init__(self, values=None, root="/home/u/.lightcycle"):
        self.values = values or {}
        self._root = root

    def data_root(self):
        return self._root

    def home_dir(self):
        return HOME

    def load_config(self):
        return self.values

    def config_path(self):
        return self._root + "/config"

    def guidance_shortcode(self):
        return "GDN"

    def context_artifact_project(self):
        return "specs"


class _ConfigEdit:
    def __init__(self, fail=()):
        self.sets = []
        self.fail = set(fail)

    def set(self, key, values):
        if key in self.fail:
            raise UseCaseError("refused %s" % key)
        self.sets.append((key, values[0]))


class _Worktrees:
    def __init__(self, repos):
        self._repos = repos

    def target_repo(self, step):
        return self._repos[step.id]


class _Base(unittest.TestCase):
    def build(self, projects=None, dirs=(), config=None, git=None, **git_kw):
        self.store = FakeStore()
        for identity, path in (projects or {"acme/app": OLD}).items():
            self.store.add_project(identity, shortcode="LC", local_path=path, facets=("a", "b"))
        self.fs = FakeFs(dirs={d: [] for d in (OLD, "/abs") + tuple(dirs)})
        self.git = git or FakeGit(**git_kw)
        self.config = config or _Config()
        self.edit = _ConfigEdit()
        self.repos = {}
        self.uc = RelocateProjectUseCase(
            self.store, self.git, self.fs, self.config, self.edit, _Worktrees(self.repos)
        )

    def claim_step(self, repo_path, item_repo="acme/app"):
        item = self.store.create_item("t", "d")
        step = self.store.create_step(role="agent", stage="write-code", item=item)
        self.store.claim_ready("agent", "w1", item=item)
        self.repos[step] = repo_path
        return step

    def calls(self, name):
        return [c for c in self.git.calls if c[0] == name]


class TestActiveStepRefusal(_Base):
    def test_mv_refuses_while_a_step_is_claimed_and_names_it(self):
        self.build()
        step = self.claim_step(OLD)
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("acme/app", NEW)
        self.assertIn(step, str(cm.exception))
        self.assertIn("acme/app", str(cm.exception))
        self.assertEqual(self.fs.renames, [])
        self.assertEqual(self.store.get_project("acme/app").local_path, OLD)

    def test_mv_refuses_for_a_guidance_workspace_step(self):
        self.build(projects={"guidance": OLD})
        step = self.claim_step(OLD)
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("guidance", NEW)
        self.assertIn(step, str(cm.exception))
        self.assertEqual(self.fs.renames, [])

    def test_mv_ignores_a_parked_step(self):
        self.build()
        step = self.claim_step(OLD)
        self.store.update_state(step, "waiting")
        self.assertIn(step, [n.id for n in self.store.steps_at_step("write-code")])
        self.assertEqual(self.store.claimed_steps(), [])
        self.uc.move("acme/app", NEW)
        self.assertEqual(self.fs.renames, [(OLD, NEW)])

    def test_prefix_refuses_the_whole_batch_for_one_active_project(self):
        self.build(projects={"a/one": OLD + "/one", "a/two": OLD + "/two", "a/three": OLD + "/three"})
        self.claim_step(OLD + "/two")
        with self.assertRaises(UseCaseError):
            self.uc.move_prefix(OLD, NEW)
        self.assertEqual(self.fs.renames, [])
        self.assertEqual(self.calls("repair_worktrees"), [])


class TestRelocation(_Base):
    def worktree_paths(self):
        return [OLD + "/.worktrees/a", OLD + "/.claude/worktrees/b", "/elsewhere/c"]

    def test_mv_repairs_in_repo_and_outside_worktrees_and_never_prunes(self):
        self.build(
            dirs=(NEW + "/.worktrees/a", NEW + "/.claude/worktrees/b", "/elsewhere/c"),
            worktrees={OLD: self.worktree_paths()},
        )
        self.uc.move("acme/app", NEW)
        repairs = self.calls("repair_worktrees")
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0][1], NEW)
        self.assertEqual(
            repairs[0][2],
            (NEW + "/.worktrees/a", NEW + "/.claude/worktrees/b", "/elsewhere/c"),
        )
        self.assertEqual(self.fs.renames, [(OLD, NEW)])
        self.assertEqual(self.calls("prune_worktrees"), [])
        self.assertEqual(self.store.get_project("acme/app").local_path, NEW)

    def test_mv_skips_a_missing_worktree_and_reports_it(self):
        self.build(
            dirs=(NEW + "/.worktrees/a",),
            worktrees={OLD: [OLD + "/.worktrees/a", OLD + "/.worktrees/gone"]},
        )
        result = self.uc.move("acme/app", NEW)
        self.assertEqual(self.calls("repair_worktrees")[0][2], (NEW + "/.worktrees/a",))
        self.assertTrue(any(NEW + "/.worktrees/gone is missing" in l for l in result.lines))

    def test_mv_rolls_back_the_rename_when_repair_fails(self):
        self.build(worktrees={OLD: [OLD + "/.worktrees/a"]}, repair_fails="fatal: no good")
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("acme/app", NEW)
        self.assertIn("fatal: no good", str(cm.exception))
        self.assertEqual(self.fs.renames, [(OLD, NEW), (NEW, OLD)])
        self.assertEqual(self.store.get_project("acme/app").local_path, OLD)

    def test_mv_fails_when_a_worktree_is_still_prunable(self):
        self.build(
            dirs=(NEW + "/.worktrees/a",),
            worktrees={OLD: [OLD + "/.worktrees/a"], NEW: [NEW + "/.worktrees/a"]},
            prunable_after_repair=(NEW + "/.worktrees/a",),
        )
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("acme/app", NEW)
        self.assertIn("still prunable", str(cm.exception))
        self.assertEqual(self.store.get_project("acme/app").local_path, OLD)

    def test_mv_keeps_shortcode_and_facets(self):
        self.build()
        self.uc.move("acme/app", NEW)
        p = self.store.get_project("acme/app")
        self.assertEqual((p.shortcode, p.facets, p.local_path), ("LC", ("a", "b"), NEW))

    def test_mv_refuses_target_that_exists_and_cross_device(self):
        self.build(dirs=(NEW,))
        self.fs._dirs[OLD] = []
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("acme/app", NEW)
        self.assertIn("already exists", str(cm.exception))
        self.build()
        self.fs.rename_error = OSError(errno.EXDEV, "cross-device")
        with self.assertRaises(UseCaseError) as cm:
            self.uc.move("acme/app", NEW)
        self.assertIn("different filesystem", str(cm.exception))
        self.assertEqual(self.store.get_project("acme/app").local_path, OLD)
        self.assertEqual(self.calls("repair_worktrees"), [])

    def test_mv_resume_when_old_gone_and_new_exists(self):
        self.build(
            dirs=(NEW, NEW + "/.worktrees/a"),
            worktrees={NEW: [OLD + "/.worktrees/a"]},
        )
        del self.fs._dirs[OLD]
        self.uc.move("acme/app", NEW)
        self.assertEqual(self.fs.renames, [])
        self.assertEqual(self.calls("repair_worktrees")[0][2], (NEW + "/.worktrees/a",))
        self.assertEqual(self.store.get_project("acme/app").local_path, NEW)

    def test_mv_refuses_when_home_is_inside_the_old_folder(self):
        self.build(config=_Config(root=OLD + "/home"))
        with self.assertRaises(UseCaseError):
            self.uc.move("acme/app", NEW)
        self.assertEqual(self.fs.renames, [])


class TestConfigRewrite(_Base):
    def test_mv_rewrites_config_values_under_the_old_folder(self):
        values = {
            "guidance-path": "~/old/agent-guidance",
            "specs-path": "/home/u/old/specs",
            "backups-dir": "/elsewhere/backups",
            "projects": "/home/u/oldish/projects",
            "callout-x": {"command": "/home/u/old/bin/x --flag"},
            "callout-y": {"command": "/home/u/oldish/y"},
        }
        old, new = "/home/u/old", "/home/u/new"
        self.build(projects={"acme/app": old}, dirs=(old, "/home/u"), config=_Config(values))
        result = self.uc.move("acme/app", new)
        self.assertEqual(
            self.edit.sets,
            [
                ("guidance-path", "~/new/agent-guidance"),
                ("specs-path", "/home/u/new/specs"),
                ("callout-x.command", "/home/u/new/bin/x --flag"),
            ],
        )
        self.assertTrue(result.config_rewritten)

    def test_config_failure_reports_the_command_to_run_and_keeps_the_move(self):
        values = {"specs-path": "/abs/old/specs"}
        self.build(config=_Config(values))
        self.edit.fail = {"specs-path"}
        result = self.uc.move("acme/app", NEW)
        self.assertTrue(any("lc config set specs-path /abs/new/specs" in l for l in result.lines))
        self.assertEqual(self.store.get_project("acme/app").local_path, NEW)


class TestPrefix(_Base):
    def test_prefix_moves_every_project_and_config_once(self):
        self.build(
            projects={
                "a/one": OLD + "/one", "a/two": OLD + "/two", "a/three": OLD + "/sub/three",
                "a/out": "/abs/other/out", "a/like": "/abs/oldish/like",
            },
            dirs=(OLD + "/one", OLD + "/two", OLD + "/sub/three"),
            config=_Config({"specs-path": "/abs/old/two"}),
        )
        result = self.uc.move_prefix(OLD, NEW)
        paths = {p.identity: p.local_path for p in self.store.list_projects()}
        self.assertEqual(paths["a/one"], NEW + "/one")
        self.assertEqual(paths["a/two"], NEW + "/two")
        self.assertEqual(paths["a/three"], NEW + "/sub/three")
        self.assertEqual(paths["a/out"], "/abs/other/out")
        self.assertEqual(paths["a/like"], "/abs/oldish/like")
        self.assertEqual(self.fs.renames, [(OLD, NEW)])
        self.assertEqual(self.edit.sets, [("specs-path", "/abs/new/two")])
        self.assertEqual(sum(1 for l in result.lines if l.startswith("moved ")), 3)


class TestSetPath(_Base):
    def test_set_path_with_no_checkout_sets_registry_and_remote_only(self):
        self.build(projects={"acme/app": None}, dirs=(NEW,), origin="git@h:acme/app.git")
        self.uc.set_path("acme/app", NEW)
        p = self.store.get_project("acme/app")
        self.assertEqual((p.local_path, p.remote), (NEW, "git@h:acme/app.git"))
        self.assertEqual(self.calls("repair_worktrees"), [])

    def test_set_path_refuses_when_the_old_path_still_exists(self):
        self.build(dirs=(NEW,))
        with self.assertRaises(UseCaseError) as cm:
            self.uc.set_path("acme/app", NEW)
        self.assertIn("lc project mv", str(cm.exception))

    def test_set_path_refuses_a_remote_mismatch_and_runs_on_a_match(self):
        self.build(dirs=(NEW,), origin="git@h:other/thing.git")
        del self.fs._dirs[OLD]
        self.store.add_project("acme/app", remote="git@h:acme/app.git")
        with self.assertRaises(UseCaseError) as cm:
            self.uc.set_path("acme/app", NEW)
        self.assertIn("not git@h:acme/app.git", str(cm.exception))
        self.build(dirs=(NEW,), origin="git@h:acme/app.git")
        del self.fs._dirs[OLD]
        self.store.add_project("acme/app", remote="git@h:acme/app.git")
        self.uc.set_path("acme/app", NEW)
        self.assertEqual(self.store.get_project("acme/app").local_path, NEW)


class TestAddIdentities(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.fs = FakeFs(files={"/home/u/.lightcycle/config": b""}, dirs={"/p": []})

        class Cfg(_Config):
            pass

        self.uc = AddProjectUseCase(self.store, FakeGit(), Cfg(), self.fs)

    def test_add_accepts_guidance_and_context_identities(self):
        r = self.uc.execute(AddProjectInput(identity="guidance", path="/p"))
        self.assertEqual((r.shortcode, r.local_path), ("GDN", "/p"))
        r = self.uc.execute(AddProjectInput(identity="specs", path="/p"))
        self.assertIsNone(r.shortcode)
        self.assertEqual(self.store.get_project("specs").local_path, "/p")

    def test_add_still_refuses_other_identities_without_a_slash(self):
        with self.assertRaises(UseCaseError) as cm:
            self.uc.execute(AddProjectInput(identity="notaslash", path="/p"))
        self.assertIn("owner/name", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
