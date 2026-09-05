import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.config import Config
from tests.support.fs_contract import FsContractBase, render_frontmatter


class TestFsAdapterContract(FsContractBase, unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def root(self):
        return self._root

    def path(self, relpath):
        return os.path.join(self._root, relpath)

    def _write(self, relpath, text_or_bytes, mode):
        full = self.path(relpath)
        dirname = os.path.dirname(full)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(full, mode) as f:
            f.write(text_or_bytes)

    def make_fs(self, files=None, dirs=None, metas=None, bodies=None, workflows=None):
        for relpath, content in (files or {}).items():
            self._write(relpath, content, "wb")
        for dirpath, children in (dirs or {}).items():
            for child in children:
                os.makedirs(self.path(os.path.join(dirpath, child)), exist_ok=True)
        for role, meta in (metas or {}).items():
            body = (bodies or {}).get(role, "")
            self._write(os.path.join("steps", "%s.md" % role), render_frontmatter(meta) + body, "w")
        for name, text in (workflows or {}).items():
            self._write(os.path.join("workflows", "%s.md" % name), text, "w")
        config = Config(environ={"LC_HOME": self._root})
        return FsAdapter(config)


if __name__ == "__main__":
    unittest.main()
