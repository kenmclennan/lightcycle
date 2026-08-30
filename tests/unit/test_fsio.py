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

    def test_workflow_meta_reads_frontmatter_summary(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        with open(os.path.join(root, "workflows", "spec-driven.md"), "w") as f:
            f.write("---\nsummary: spec to merged\nwhen-to-use: default build flow\n---\nentry: x\n")
        self.assertEqual(
            FsAdapter(None).workflow_meta("spec-driven", root),
            {"summary": "spec to merged", "when-to-use": "default build flow"},
        )

    def test_workflow_meta_without_frontmatter_is_empty(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "workflows"))
        with open(os.path.join(root, "workflows", "bare.md"), "w") as f:
            f.write("entry: x\n\nedges:\n  x  done  y\n")
        self.assertEqual(FsAdapter(None).workflow_meta("bare", root), {})

    def test_fake_fs_no_workflows_seeded_is_empty(self):
        self.assertEqual(FakeFs().workflow_names(), [])


class TestReadFrom(unittest.TestCase):
    def test_reads_from_the_start_when_offset_is_zero(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = FsAdapter(None)
        data, offset = adapter.read_from(path, 0)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_reads_only_the_bytes_written_since_the_offset(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\n")
        adapter = FsAdapter(None)
        _data, offset = adapter.read_from(path, 0)
        with open(path, "a") as f:
            f.write("line two\n")
        data, new_offset = adapter.read_from(path, offset)
        self.assertEqual(data, b"line two\n")
        self.assertEqual(new_offset, offset + len(b"line two\n"))

    def test_missing_file_reads_nothing_and_keeps_the_offset(self):
        adapter = FsAdapter(None)
        data, offset = adapter.read_from(os.path.join(tempfile.mkdtemp(), "gone.log"), 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 5)

    def test_fake_fs_slices_seeded_content_from_the_offset(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_from("/l/worker.log", len(b"line one\n"))
        self.assertEqual(data, b"line two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_unknown_path_reads_nothing(self):
        fs = FakeFs()
        data, offset = fs.read_from("/l/missing.log", 0)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)


class TestReadTail(unittest.TestCase):
    def test_smaller_than_max_bytes_returns_the_entire_content(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = FsAdapter(None)
        data, offset = adapter.read_tail(path, 1024)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_larger_than_max_bytes_returns_only_the_trailing_bytes(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = FsAdapter(None)
        data, offset = adapter.read_tail(path, len(b"line two\n"))
        self.assertEqual(data, b"line two\n")
        self.assertNotIn(b"line one", data)
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_offset_lines_up_exactly_with_a_following_read_from(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = FsAdapter(None)
        _data, offset = adapter.read_tail(path, len(b"line two\n"))
        with open(path, "a") as f:
            f.write("line three\n")
        data, new_offset = adapter.read_from(path, offset)
        self.assertEqual(data, b"line three\n")
        self.assertEqual(new_offset, offset + len(b"line three\n"))

    def test_missing_file_reads_nothing_with_zero_offset(self):
        adapter = FsAdapter(None)
        data, offset = adapter.read_tail(os.path.join(tempfile.mkdtemp(), "gone.log"), 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)

    def test_fake_fs_smaller_than_max_bytes_returns_the_entire_content(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_tail("/l/worker.log", 1024)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_larger_than_max_bytes_returns_only_the_trailing_bytes(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_tail("/l/worker.log", len(b"line two\n"))
        self.assertEqual(data, b"line two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_unknown_path_reads_nothing_with_zero_offset(self):
        fs = FakeFs()
        data, offset = fs.read_tail("/l/missing.log", 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)


class TestExists(unittest.TestCase):
    def test_existing_file_exists(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "spec.md")
        open(path, "w").close()
        self.assertTrue(FsAdapter(None).exists(path))

    def test_missing_file_does_not_exist(self):
        root = tempfile.mkdtemp()
        self.assertFalse(FsAdapter(None).exists(os.path.join(root, "gone.md")))

    def test_existing_directory_exists(self):
        root = tempfile.mkdtemp()
        self.assertTrue(FsAdapter(None).exists(root))

    def test_fake_fs_reports_seeded_files_and_dirs(self):
        fs = FakeFs(files={"/s/spec.md": b"x"}, dirs={"/root": ["blueprint"]})
        self.assertTrue(fs.exists("/s/spec.md"))
        self.assertTrue(fs.exists("/root"))
        self.assertFalse(fs.exists("/s/gone.md"))


if __name__ == "__main__":
    unittest.main()
