import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter, workflow_names
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
        self.assertEqual(FsAdapter(None).workflow_names(root), ["build"])

    def test_adapter_no_root_is_empty(self):
        self.assertEqual(FsAdapter(None).workflow_names(None), [])

    def test_fake_fs_lists_seeded_workflow_names(self):
        fs = FakeFs(workflows={"build": "entry: code\n", "spec-driven": "entry: write\n"})
        self.assertEqual(fs.workflow_names(), ["build", "spec-driven"])
        self.assertEqual(fs.workflow_text("build"), "entry: code\n")

    def test_fake_fs_no_workflows_seeded_is_empty(self):
        self.assertEqual(FakeFs().workflow_names(), [])


if __name__ == "__main__":
    unittest.main()
