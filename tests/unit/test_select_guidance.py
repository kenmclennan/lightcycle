import os
import tempfile
import unittest
from pathlib import Path

from lightcycle.application.flow.select_guidance import SelectGuidanceUseCase
from lightcycle.config import Config
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

ROOT = "/kb"


def _cfg(budget="6144"):
    p = os.path.join(tempfile.mkdtemp(), "config")
    Path(p).write_text("guidance-budget-bytes: %s\n" % budget)
    return Config(environ={"LC_CONFIG": p})


def _entry(status="stable", verified="ken", facets=None, steps=None, body="body", type_="Guidance"):
    applies = []
    if facets is not None:
        applies.append("  facets: [%s]" % ", ".join(facets))
    if steps is not None:
        applies.append("  steps: [%s]" % ", ".join(steps))
    lines = ["---", "type: %s" % type_, "status: %s" % status]
    if verified is not None:
        lines.append("verified: %s" % verified)
    lines.append("applies-to:")
    lines += applies
    lines += ["---", "", body, ""]
    return "\n".join(lines).encode()


def _setup(files, project_facets=("kotlin",), budget="6144", repo="acme/x"):
    store = FakeStore()
    store.add_project("guidance", local_path=ROOT)
    store.add_project("acme/x", facets=project_facets)
    item = store.create_item("t", "d")
    if repo:
        store.add_artifact(item, "repo", repo)
    fs = FakeFs(files={"%s/%s" % (ROOT, k): v for k, v in files.items()}, dirs={ROOT: []})
    return SelectGuidanceUseCase(store, fs, _cfg(budget)), item


class TestSelectGuidance(unittest.TestCase):
    def test_acceptance_fixture_delivers_exactly_the_matching_entries_in_order(self):
        files = {
            "all/zeta.md": _entry(body="zeta"),
            "all/alpha.md": _entry(body="alpha"),
            "kt/stepped.md": _entry(facets=["kotlin"], steps=["write-code"], body="stepped"),
            "kt/origin.md": _entry(steps=["acme/write-code"], body="origin"),
            "kt/other-origin.md": _entry(steps=["other/write-code"], body="no"),
            "kt/other-step.md": _entry(steps=["review-code"], body="no"),
            "kt/mismatch.md": _entry(facets=["python"], body="no"),
            "kt/draft.md": _entry(status="draft", body="no"),
            "kt/unverified.md": _entry(verified=None, body="no"),
            "kt/notes.md": _entry(type_="Concept", body="no"),
            "index.md": _entry(body="no"),
        }
        use, item = _setup(files)
        sel = use.execute(item, "write-code", "acme/wf@abc", "S.1")
        self.assertEqual(
            sel.delivered, ("kt/origin", "kt/stepped", "all/alpha", "all/zeta"))
        self.assertEqual(sel.skipped, ())
        self.assertEqual(sel.notes, ())
        self.assertTrue(sel.section.startswith("## Guidance for this project"))
        self.assertNotIn("no\n", sel.section)
        self.assertIn("`lc attach S.1 guidance-cited ", sel.section)
        self.assertTrue(sel.section.rstrip().endswith("never one you only read."))

    def test_budget_skips_whole_and_lists_the_excess(self):
        files = {
            "a.md": _entry(body="x" * 60), "b.md": _entry(body="x" * 50),
            "c.md": _entry(body="x" * 40), "d.md": _entry(body="x"),
        }
        use, item = _setup(files, budget="100")
        sel = use.execute(item, "write-code", None, "S.1")
        self.assertEqual(sel.delivered, ("a", "c"))
        self.assertEqual(sel.skipped, ("b", "d"))
        self.assertNotIn("### b", sel.section)
        self.assertNotIn("### d", sel.section)

    def test_no_matches_is_an_empty_section(self):
        use, item = _setup({"a.md": _entry(facets=["python"])})
        sel = use.execute(item, "write-code", None, "S.1")
        self.assertEqual((sel.section, sel.delivered, sel.skipped), ("", (), ()))

    def test_item_without_a_repo_gets_only_facet_free_entries(self):
        files = {"a.md": _entry(facets=["kotlin"]), "b.md": _entry()}
        use, item = _setup(files, repo=None)
        self.assertEqual(use.execute(item, "s", None, "S.1").delivered, ("b",))

    def test_item_with_an_unregistered_repo_gets_only_facet_free_entries(self):
        files = {"a.md": _entry(facets=["kotlin"]), "b.md": _entry()}
        use, item = _setup(files, repo="acme/unknown")
        self.assertEqual(use.execute(item, "s", None, "S.1").delivered, ("b",))

    def test_unregistered_guidance_repo_yields_one_note(self):
        store = FakeStore()
        item = store.create_item("t", "d")
        sel = SelectGuidanceUseCase(store, FakeFs(), _cfg()).execute(item, "s", None, "S.1")
        self.assertEqual((sel.section, len(sel.notes)), ("", 1))

    def test_missing_guidance_path_yields_one_note(self):
        store = FakeStore()
        store.add_project("guidance", local_path="/gone")
        item = store.create_item("t", "d")
        sel = SelectGuidanceUseCase(store, FakeFs(), _cfg()).execute(item, "s", None, "S.1")
        self.assertEqual((sel.section, len(sel.notes)), ("", 1))
        self.assertIn("/gone", sel.notes[0])

    def test_a_malformed_or_unreadable_file_is_noted_and_the_rest_delivered(self):
        files = {
            "good.md": _entry(body="good"),
            "bad-list.md": b"---\ntype: Guidance\nstatus: stable\nverified: k\napplies-to:\n  facets:\n---\nb\n",
            "no-applies.md": b"---\ntype: Guidance\nstatus: stable\nverified: k\n---\nb\n",
            "unclosed.md": b"---\ntype: Guidance\nstatus: stable\n",
            "binary.md": b"\xff\xfe\x00",
        }
        use, item = _setup(files)
        sel = use.execute(item, "s", None, "S.1")
        self.assertEqual(sel.delivered, ("good",))
        self.assertEqual(sorted(n.split(":")[0] for n in sel.notes),
                         ["bad-list", "binary", "no-applies", "unclosed"])

    def test_dot_directories_are_not_scanned(self):
        use, item = _setup({".git/x.md": _entry(), "ok.md": _entry()})
        self.assertEqual(use.execute(item, "s", None, "S.1").delivered, ("ok",))


if __name__ == "__main__":
    unittest.main()
