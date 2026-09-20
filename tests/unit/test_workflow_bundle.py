import os
import tempfile
import unittest

from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter, parse_step, workflow_names
from tests.support.fake_fs import FakeFs


class TestWorkflowNames(unittest.TestCase):
    def test_module_level_lists_workflow_files(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        open(os.path.join(root, "workflows", "build.md"), "w").close()
        open(os.path.join(root, "workflows", "spec-driven.md"), "w").close()
        self.assertEqual(workflow_names([root]), ["build", "spec-driven"])

    def test_missing_workflows_dir_is_empty(self):
        self.assertEqual(workflow_names([tempfile.mkdtemp()]), [])

    def test_adapter_wraps_a_single_root(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        open(os.path.join(root, "workflows", "build.md"), "w").close()
        self.assertEqual(WorkflowBundleAdapter().workflow_names(root), ["build"])

    def test_adapter_no_root_is_empty(self):
        self.assertEqual(WorkflowBundleAdapter().workflow_names(None), [])

    def test_fake_fs_lists_seeded_workflow_names(self):
        fs = FakeFs(workflows={"build": "entry: code\n", "spec-driven": "entry: write\n"})
        self.assertEqual(fs.workflow_names(), ["build", "spec-driven"])
        self.assertEqual(fs.workflow_text("build"), "entry: code\n")

    def test_workflow_meta_reads_frontmatter_summary(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        with open(os.path.join(root, "workflows", "spec-driven.md"), "w") as f:
            f.write("---\nsummary: spec to merged\nwhen-to-use: default build flow\n---\nentry: x\n")
        self.assertEqual(
            WorkflowBundleAdapter().workflow_meta("spec-driven", root),
            {"summary": "spec to merged", "when-to-use": "default build flow"},
        )

    def test_workflow_meta_without_frontmatter_is_empty(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        with open(os.path.join(root, "workflows", "bare.md"), "w") as f:
            f.write("entry: x\n\nedges:\n  x  done  y\n")
        self.assertEqual(WorkflowBundleAdapter().workflow_meta("bare", root), {})

    def test_fake_fs_no_workflows_seeded_is_empty(self):
        self.assertEqual(FakeFs().workflow_names(), [])


def _bundle(files):
    root = tempfile.mkdtemp()
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
        with open(os.path.join(root, rel), "w") as f:
            f.write(text)
    return root


class TestIncludeCycles(unittest.TestCase):
    def test_self_including_fragment_names_the_cycle(self):
        root = _bundle({"fragments/loop.md": "@include loop\n", "steps/s.md": "@include loop\n"})
        with self.assertRaises(ValueError) as cm:
            parse_step(root, "s")
        self.assertIn("'loop'", str(cm.exception))
        self.assertIn("loop -> loop", str(cm.exception))

    def test_mutually_including_fragments_name_the_chain(self):
        root = _bundle(
            {
                "fragments/a.md": "@include b\n",
                "fragments/b.md": "@include a\n",
                "steps/s.md": "@include a\n",
            }
        )
        with self.assertRaises(ValueError) as cm:
            parse_step(root, "s")
        self.assertIn("a -> b -> a", str(cm.exception))

    def test_repeated_non_cyclic_include_resolves(self):
        root = _bundle({"fragments/x.md": "hi\n", "steps/s.md": "@include x\n@include x\n"})
        self.assertEqual(parse_step(root, "s").body.count("hi"), 2)


if __name__ == "__main__":
    unittest.main()
