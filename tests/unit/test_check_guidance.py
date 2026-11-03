import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.application.errors import UseCaseError
from lightcycle.application.inspect.check_guidance import CheckGuidanceUseCase
from lightcycle.container import Container
from lightcycle.domain.work.worker_permissions import WORKER_VERBS, worker_permitted
from tests.support.fake_fs import FakeFs
from lightcycle.ports.store import StoreUnreadableError
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore
from tests.support.installed_steps import AGENT, graph, installed
from tests.unit.test_guidance_conventions import entry
from tests.unit.test_select_guidance import _cfg

ROOT = "/kb"


def _fs(files):
    return FakeFs(files={"%s/%s" % (ROOT, p): t.encode() for p, t in files.items()})


_ORIGINS = {"acme": ("sha1", {"write-code": AGENT}, {"wf": graph(("write-code", "done", "x"))})}


def _store(projects):
    store = FakeStore()
    store.add_project("guidance", local_path=ROOT)
    for identity, facets in projects:
        store.add_project(identity, facets=facets)
    return store


def _sized(size, applies="  facets: [kotlin]\n  steps: [write-code]"):
    return entry(status="stable", applies=applies, body="x" * size + "\n")


class _Unreadable(FakeStore):
    def list_projects(self):
        raise StoreUnreadableError("live store refused")


class _Rig(unittest.TestCase):
    def _full(self, rows, files, base_files=None, mode="final", base="origin/main",
              projects=(("acme/x", ("kotlin",)),), budget="100", origins=_ORIGINS,
              store=None, config=None, **git_kw):
        git = FakeGit(
            changed={(ROOT, base): rows},
            ref_files={base: {k: v.encode() for k, v in (base_files or {}).items()}}, **git_kw)
        source, bundle = installed(origins)
        use_case = CheckGuidanceUseCase(
            git, _fs(files), store if store is not None else _store(projects), source, bundle,
            config if config is not None else _cfg(budget))
        return use_case.execute(ROOT, mode, base), git

    def _run(self, rows, files, **kw):
        result, git = self._full(rows, files, **kw)
        return result[:2], git

class TestCheckGuidanceUseCase(_Rig):
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
            self._run([], {}, raises=("changed_paths",))

    def test_changed_file_missing_from_the_tree_raises(self):
        with self.assertRaises(UseCaseError):
            self._run([("A", "a.md")], {})

    def test_deleted_file_unreadable_at_base_raises(self):
        with self.assertRaises(UseCaseError):
            self._run([("D", "a.md")], {})


_PAGES = {"kotlin.md": "x", "python.md": "x"}


class TestBudgetCheck(_Rig):
    def test_new_entry_that_does_not_fit_fails_naming_it(self):
        base = {"a.md": _sized(60), **_PAGES}
        files = {**base, "b.md": _sized(60)}
        (failures, checked, warnings), _ = self._full([("A", "b.md")], files, base_files=base)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].startswith("budget: project acme/x, step acme/write-code"))
        self.assertIn("matched 120 bytes against 100", failures[0])
        self.assertTrue(failures[0].endswith("newly skips: b"))
        self.assertEqual(warnings, [])

    def test_retag_that_pushes_a_delivered_entry_out_fails_naming_it(self):
        unscoped = "  facets: [kotlin]"
        base = {
            "a.md": _sized(60, unscoped),
            "b.md": _sized(50, "  facets: [kotlin]\n  steps: [other-step]"),
            **_PAGES,
        }
        files = {**base, "b.md": _sized(50)}
        (failures, _, _), _ = self._full([("M", "b.md")], files, base_files=base)
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0].endswith("newly skips: a"))

    def test_preexisting_overflow_is_a_warning_when_another_entry_changes(self):
        base = {"a.md": _sized(60), "b.md": _sized(60), **_PAGES}
        files = {**base, "d.md": entry()}
        (failures, checked, warnings), _ = self._full([("A", "d.md")], files, base_files=base)
        self.assertEqual((failures, checked), ([], 1))
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("warning: project acme/x, step acme/write-code"))
        self.assertTrue(warnings[0].endswith("skipped: b"))

    def test_one_worsened_pair_and_one_preexisting_pair(self):
        py = "  facets: [python]\n  steps: [write-code]"
        base = {"p1.md": _sized(60, py), "p2.md": _sized(60, py), **_PAGES}
        files = {**base, "k1.md": _sized(60), "k2.md": _sized(60)}
        (failures, _, warnings), _ = self._full(
            [("A", "k1.md"), ("A", "k2.md")], files, base_files=base,
            projects=(("py/x", ("python",)), ("kt/x", ("kotlin",))))
        self.assertEqual(len(failures), 1)
        self.assertIn("project kt/x", failures[0])
        self.assertEqual(len(warnings), 1)
        self.assertIn("project py/x", warnings[0])

    def test_entry_skipped_at_base_that_grows_and_is_still_skipped_passes(self):
        base = {"a.md": _sized(60), "b.md": _sized(60), **_PAGES}
        files = {**base, "b.md": _sized(70)}
        (failures, _, warnings), _ = self._full([("M", "b.md")], files, base_files=base)
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1)

    def test_no_registered_projects_passes_silently(self):
        files = {"a.md": _sized(600), **_PAGES}
        (failures, _, warnings), _ = self._full([("A", "a.md")], files, projects=())
        self.assertEqual((failures, warnings), ([], []))

    def test_unreadable_budget_passes_with_a_skip_warning(self):
        files = {"a.md": _sized(600), **_PAGES}
        (failures, _, warnings), _ = self._full([("A", "a.md")], files, budget="-1")
        self.assertEqual(failures, [])
        self.assertTrue(warnings[0].startswith("budget check skipped"))

    def test_unreadable_store_passes_with_a_skip_warning(self):
        files = {"a.md": _sized(600), **_PAGES}
        (failures, _, warnings), _ = self._full(
            [("A", "a.md")], files, store=_Unreadable())
        self.assertEqual(failures, [])
        self.assertTrue(warnings[0].startswith("budget check skipped"))

    def test_no_installed_agent_steps_passes_silently(self):
        files = {"a.md": _sized(600), **_PAGES}
        (failures, _, warnings), _ = self._full([("A", "a.md")], files, origins={})
        self.assertEqual((failures, warnings), ([], []))


def _universal(size, steps="  steps: []"):
    return entry(status="stable", applies=steps, body="x" * size + "\n")


_TWO_STEPS = {"acme": ("sha1", {"a": AGENT, "b": AGENT}, {"wf": graph(("a", "b", "x"), ("b", "done", "x"))})}


class TestUniversalWarning(_Rig):
    def test_new_universal_entry_warns_with_size_step_total_and_budget(self):
        files = {"a.md": _universal(30)}
        (failures, checked, warnings), _ = self._full([("A", "a.md")], files)
        self.assertEqual((failures, checked), ([], 1))
        self.assertEqual(warnings, [
            "warning: universal entry a is 30 bytes; step acme/write-code receives the most universal bytes, 30 of 100"])

    def test_steps_tag_is_ignored(self):
        files = {"a.md": _universal(30, "  steps: [write-code]")}
        (_, _, warnings), _ = self._full([("A", "a.md")], files)
        self.assertEqual(len(warnings), 1)
        self.assertIn("universal entry a", warnings[0])

    def test_names_the_heaviest_step_and_swapping_sizes_moves_it(self):
        files = {
            "u1.md": _universal(10),
            "u2.md": _universal(30, "  steps: [a]"),
            "u3.md": _universal(20, "  steps: [b]"),
        }
        (_, _, warnings), _ = self._full([("A", "u1.md")], files, origins=_TWO_STEPS)
        self.assertTrue(warnings[0].endswith("step acme/a receives the most universal bytes, 40 of 100"))
        files["u2.md"], files["u3.md"] = files["u3.md"], files["u2.md"]
        files["u2.md"] = files["u2.md"].replace("steps: [b]", "steps: [a]")
        files["u3.md"] = files["u3.md"].replace("steps: [a]", "steps: [b]")
        (_, _, warnings), _ = self._full([("A", "u1.md")], files, origins=_TWO_STEPS)
        self.assertIn("step acme/b receives the most universal bytes", warnings[0])

    def test_no_installed_steps_takes_the_second_form_and_sums_all(self):
        files = {"a.md": _universal(10), "b.md": _universal(20)}
        (_, _, warnings), _ = self._full([("A", "a.md")], files, origins={})
        self.assertEqual(warnings, [
            "warning: universal entries total 30 of 100 bytes; universal entry a is 10 bytes"])

    def test_unchanged_universal_entry_is_counted_but_not_named(self):
        files = {"a.md": _universal(10), "b.md": _universal(20)}
        (_, _, warnings), _ = self._full([("A", "a.md")], files)
        self.assertEqual(len(warnings), 1)
        self.assertIn("universal entry a ", warnings[0])
        self.assertTrue(warnings[0].endswith("30 of 100"))

    def test_draft_and_faceted_entries_print_nothing(self):
        files = {
            "d.md": entry(status="draft", applies="  steps: []"),
            "f.md": _sized(10),
            **_PAGES,
        }
        (failures, _, warnings), _ = self._full([("A", "d.md"), ("A", "f.md")], files)
        self.assertEqual((failures, warnings), ([], []))

    def test_warns_when_no_project_is_registered(self):
        (failures, _, warnings), _ = self._full([("A", "a.md")], {"a.md": _universal(10)}, projects=())
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1)

    def test_unreadable_budget_prints_only_the_skip_note(self):
        (failures, _, warnings), _ = self._full([("A", "a.md")], {"a.md": _universal(10)}, budget="-1")
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("budget check skipped"))

    def test_overflow_warnings_print_before_universal_warnings(self):
        base = {"a.md": _sized(60), "b.md": _sized(60), **_PAGES}
        files = {**base, "u.md": _universal(5)}
        (failures, _, warnings), _ = self._full([("A", "u.md")], files, base_files=base)
        self.assertEqual(failures, [])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(warnings[0].startswith("warning: project "))
        self.assertTrue(warnings[1].startswith("warning: universal entry u"))


class TestGuidanceCheckCommand(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _call(self, argv, git, fs):
        source, bundle = installed({})
        cli_mod.set_container(Container(
            config=_cfg(), git=git, store=_store(()), spawner=object(), workers=object(),
            fs=fs, github=object(), lock=object(), breaker=object(),
            workflow_source=source, workflow_bundle=bundle,
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance_check(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_a_remaining_overflow_prints_a_warning_and_exits_zero(self):
        source, bundle = installed(_ORIGINS)
        cli_mod.set_container(Container(
            config=_cfg("100"), git=FakeGit(
                changed={(ROOT, "main"): [("A", "d.md")]},
                ref_files={"main": {
                    "a.md": _sized(60).encode(), "b.md": _sized(60).encode(),
                    "kotlin.md": b"x", "python.md": b"x"}}),
            store=_store([("acme/x", ("kotlin",))]), spawner=object(), workers=object(),
            fs=_fs({"a.md": _sized(60), "b.md": _sized(60), "d.md": entry(), **_PAGES}),
            github=object(), lock=object(), breaker=object(),
            workflow_source=source, workflow_bundle=bundle,
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli_mod.cmd_guidance_check(["--dir", ROOT, "--mode", "draft", "--base", "main"])
        lines = out.getvalue().splitlines()
        self.assertEqual(rc, 0)
        self.assertTrue(lines[0].startswith("warning: project acme/x"))
        self.assertEqual(lines[-1], "1 changed file(s) clean (draft mode)")

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


def _projected(values):
    return entry(status="stable", applies="  projects: [%s]" % values, body="x\n")


class TestUnregisteredProjectWarning(_Rig):
    def _warnings(self, values, rows=(("A", "a.md"),), **kw):
        (failures, _, warnings), _ = self._full(
            list(rows), {"a.md": _projected(values)}, budget="1000", **kw)
        return failures, [w for w in warnings if "names no project" in w]

    def test_registered_identity_and_short_name_warn_nothing(self):
        self.assertEqual(self._warnings("acme/x, x"), ([], []))

    def test_unregistered_identity_and_bare_name_each_warn_once_without_failing(self):
        failures, warns = self._warnings("ghost/repo")
        self.assertEqual(failures, [])
        self.assertEqual(warns, ["warning: a.md: project 'ghost/repo' names no project registered on this machine"])
        failures, warns = self._warnings("ghost")
        self.assertEqual(failures, [])
        self.assertEqual(warns, ["warning: a.md: project 'ghost' names no project registered on this machine"])

    def test_mixed_values_warn_only_for_the_unregistered_one(self):
        _, warns = self._warnings("acme/x, ghost")
        self.assertEqual(warns, ["warning: a.md: project 'ghost' names no project registered on this machine"])

    def test_unchanged_entry_warns_nothing(self):
        files = {"a.md": _projected("ghost"), "b.md": _sized(5), **_PAGES}
        (_, _, warnings), _ = self._full([("A", "b.md")], files, budget="1000")
        self.assertEqual([w for w in warnings if "names no project" in w], [])

    def test_unreadable_registry_warns_nothing_and_does_not_fail(self):
        failures, warns = self._warnings("ghost", store=_Unreadable())
        self.assertEqual((failures, warns), ([], []))
