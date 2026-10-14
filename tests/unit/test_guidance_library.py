import unittest

from lightcycle.application.services.guidance_library import GuidanceLibrary
from tests.support.fake_git import FakeGit
from tests.unit.test_select_guidance import _entry

ROOT = "/kb"


def _git(files, ref="origin/main", origin="git@x:kb.git"):
    return FakeGit(origin=origin, ref=ref, ref_files={"origin/main": files, "main": files})


class TestGuidanceLibrary(unittest.TestCase):
    def test_loads_entries_and_lists_files_from_the_ref(self):
        git = _git({"a.md": _entry(), "kotlin.md": b"# kotlin\n", "index.md": b"x"})
        lib = GuidanceLibrary(git)
        entries, problems = lib.load(ROOT)
        self.assertEqual([e.id for e in entries], ["a"])
        self.assertEqual(problems, [])
        self.assertEqual(lib.files(ROOT), ["a.md", "index.md", "kotlin.md"])

    def test_a_file_only_in_the_working_tree_is_not_loaded(self):
        git = _git({"on-origin.md": _entry()})
        git._ref_files["feature-branch"] = {"branch-only.md": _entry()}
        entries, _ = GuidanceLibrary(git).load(ROOT)
        self.assertEqual([e.id for e in entries], ["on-origin"])

    def test_no_ref_for_an_unfetched_origin_says_so(self):
        entries, problems = GuidanceLibrary(_git({}, ref=None)).load(ROOT)
        self.assertEqual(entries, [])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], "guidance")
        self.assertIn("not been fetched", problems[0][1])

    def test_no_ref_without_an_origin_says_no_default_branch(self):
        _, problems = GuidanceLibrary(_git({}, ref=None, origin=None)).load(ROOT)
        self.assertIn("no default branch", problems[0][1])

    def test_per_file_problems_are_reported(self):
        git = _git({
            "good.md": _entry(),
            "binary.md": b"\xff\xfe\x00",
            "unclosed.md": b"---\ntype: Guidance\nstatus: stable\n",
            "no-applies.md": b"---\ntype: Guidance\nstatus: stable\nverified: k\n---\nb\n",
        })
        entries, problems = GuidanceLibrary(git).load(ROOT)
        self.assertEqual([e.id for e in entries], ["good"])
        self.assertEqual(sorted(name for name, _ in problems),
                         ["binary", "no-applies", "unclosed"])


if __name__ == "__main__":
    unittest.main()
