import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.check_guidance import CheckGuidanceUseCase
from lightcycle.container import Container
from lightcycle.domain.work.worker_permissions import WORKER_VERBS, worker_permitted
from tests.support.fake_fs import FakeFs
from tests.support.fake_git import FakeGit
from tests.unit.test_guidance_conventions import entry

ROOT = "/kb"


def _fs(files):
    return FakeFs(files={"%s/%s" % (ROOT, p): t.encode() for p, t in files.items()})


class TestCheckGuidanceUseCase(unittest.TestCase):
    def _run(self, rows, files, base_files=None, mode="final", base="origin/main", **git_kw):
        git = FakeGit(
            changed={(ROOT, base): rows}, ref_files={base: {k: v.encode() for k, v in (base_files or {}).items()}}, **git_kw
        )
        return CheckGuidanceUseCase(git, _fs(files)).execute(ROOT, mode, base), git

    def test_clean_changed_entry(self):
        (failures, checked), git = self._run(
            [("A", "a.md"), ("M", "index.md")],
            {"a.md": entry(), "kotlin.md": "---\ntitle: k\n---\n"},
        )
        self.assertEqual((failures, checked), ([], 2 - 1))
        self.assertIn(("changed_paths", ROOT, "origin/main"), git.calls)

    def test_rows_are_checked_in_git_order(self):
        bad = entry(status="live")
        (failures, _), _ = self._run(
            [("A", "a.md"), ("A", "b.md")],
            {"a.md": bad, "b.md": bad, "kotlin.md": "---\nx: y\n---\n"},
        )
        self.assertEqual([f.split(":")[0] for f in failures], ["a.md", "b.md"])

    def test_deleted_guidance_entry_fails(self):
        (failures, checked), _ = self._run(
            [("D", "a.md")], {}, base_files={"a.md": entry()},
        )
        self.assertEqual(
            failures, ["a.md: entry deleted - retire it with status: deprecated instead"],
        )
        self.assertEqual(checked, 0)

    def test_deleted_non_guidance_page_is_ignored(self):
        (failures, _), _ = self._run(
            [("D", "a.md")], {}, base_files={"a.md": "---\ntitle: x\n---\n"},
        )
        self.assertEqual(failures, [])

    def test_facet_page_found_under_a_normal_directory(self):
        (failures, _), _ = self._run(
            [("A", "a.md")],
            {"a.md": entry(), "languages/kotlin.md": "x"},
        )
        self.assertEqual(failures, [])

    def test_facet_page_only_under_a_dot_directory_is_not_found(self):
        (failures, _), _ = self._run(
            [("A", "a.md")],
            {"a.md": entry(), ".hidden/kotlin.md": "x"},
        )
        self.assertEqual(failures, ["a.md: facet 'kotlin' has no concept page kotlin.md"])

    def test_context_only_reads_the_base_copy(self):
        base = entry(status="stable", extra="verified: ken\n", purpose="old")
        head = entry(status="stable", extra="verified: ken\n", purpose="new")
        (failures, _), _ = self._run(
            [("M", "a.md")], {"a.md": head, "kotlin.md": "x"},
            base_files={"a.md": base}, mode="draft",
        )
        self.assertEqual(failures, [])

    def test_uncommitted_markdown_fails_without_reading_the_diff(self):
        (failures, checked), _ = self._run(
            [("A", "a.md")], {"a.md": entry()}, uncommitted={ROOT: ["a.md", "notes.txt"]},
        )
        self.assertEqual(checked, 0)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("a.md: uncommitted change"))

    def test_unreadable_status_raises_use_case_error(self):
        with self.assertRaises(UseCaseError):
            self._run([], {}, raises=("uncommitted_paths",))

    def test_failing_diff_raises_use_case_error(self):
        with self.assertRaises(UseCaseError):
            CheckGuidanceUseCase(FakeGit(raises=("changed_paths",)), _fs({})).execute(
                ROOT, "final", "nope"
            )

    def test_changed_file_missing_from_the_tree_raises(self):
        with self.assertRaises(UseCaseError):
            self._run([("A", "a.md")], {})

    def test_deleted_file_unreadable_at_base_raises(self):
        with self.assertRaises(UseCaseError):
            self._run([("D", "a.md")], {})


class TestGuidanceCheckCommand(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _call(self, argv, git, fs):
        cli_mod.set_container(Container(
            config=object(), git=git, store=object(), spawner=object(), workers=object(),
            fs=fs, github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance_check(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_defaults_to_final_mode_against_origin_main_and_exits_clean(self):
        git = FakeGit(changed={(".", "origin/main"): [("A", "a.md")]})
        fs = FakeFs(files={"./a.md": entry(status="stable", extra="verified: k\n").encode(),
                           "./kotlin.md": b"x"})
        rc, out, err = self._call([], git, fs)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "1 changed file(s) clean (final mode)")

    def test_final_default_accepts_stable_without_verified(self):
        git = FakeGit(changed={(".", "origin/main"): [("A", "a.md")]})
        fs = FakeFs(files={"./a.md": entry(status="stable").encode(), "./kotlin.md": b"x"})
        rc, out, _ = self._call([], git, fs)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "1 changed file(s) clean (final mode)")

    def test_draft_mode_flag(self):
        git = FakeGit(changed={(ROOT, "main"): [("A", "a.md")]})
        fs = _fs({"a.md": entry(extra="verified: k\n"), "kotlin.md": "x"})
        rc, out, _ = self._call(["--dir", ROOT, "--mode", "draft", "--base", "main"], git, fs)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "1 changed file(s) clean (draft mode)")

    def test_nothing_changed_says_so_without_the_word_clean(self):
        rc, out, err = self._call([], FakeGit(), FakeFs())
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.strip(), "no guidance files changed between origin/main and HEAD (final mode)")
        self.assertNotIn("clean", out)

    def test_unresolvable_base_exits_one_with_the_reason(self):
        rc, out, err = self._call(["--base", "nope"], FakeGit(raises=("changed_paths",)), FakeFs())
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertIn("changed_paths", err)


class TestWorkerPermission(unittest.TestCase):
    def test_a_worker_may_run_guidance_check(self):
        self.assertIn("guidance-check", WORKER_VERBS)
        self.assertTrue(worker_permitted("guidance-check", {}))


class TestGuidanceConventionsCommand(unittest.TestCase):
    def test_prints_the_text_init_writes_byte_for_byte(self):
        from lightcycle.domain.guidance.conventions import CONVENTIONS_TEXT

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_mod.cmd_guidance_conventions([])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), CONVENTIONS_TEXT)

    def test_a_worker_may_run_it(self):
        self.assertTrue(worker_permitted("guidance-conventions", {}))
