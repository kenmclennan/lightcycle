import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.gh_shim import GhShimAdapter
from lightcycle.config import Config


class TestGhShimAdapter(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.env = {"LC_HOME": self.home, "PATH": "/usr/bin:/bin"}
        self.adapter = GhShimAdapter(Config(environ=self.env))

    def test_install_writes_an_executable_shim_and_puts_its_directory_first_on_path(self):
        directory = self.adapter.install()

        self.assertEqual(directory, os.path.join(self.home, "shims"))
        self.assertTrue(os.access(os.path.join(directory, "gh"), os.X_OK))
        self.assertEqual(self.env["PATH"], "%s:/usr/bin:/bin" % directory)

    def test_installing_twice_leaves_path_unchanged(self):
        self.adapter.install()
        once = self.env["PATH"]

        self.adapter.install()

        self.assertEqual(self.env["PATH"], once)


if __name__ == "__main__":
    unittest.main()
