import os
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from tests.support.fake_fs import FakeFs


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
