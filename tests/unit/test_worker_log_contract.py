import os
import shutil
import tempfile
import unittest

from lightcycle.adapters.worker_log import WorkerLogAdapter
from lightcycle.config import Config
from tests.support.fs_contract import WorkerLogContractBase


class TestWorkerLogAdapterContract(WorkerLogContractBase, unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def root(self):
        return self._root

    def path(self, relpath):
        return os.path.join(self._root, relpath)

    def _write(self, relpath, content):
        full = self.path(relpath)
        dirname = os.path.dirname(full)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)

    def make_fs(self, files=None, dirs=None, metas=None, bodies=None, workflows=None):
        for relpath, content in (files or {}).items():
            self._write(relpath, content)
        config = Config(environ={"LC_HOME": self._root})
        return WorkerLogAdapter(config)


if __name__ == "__main__":
    unittest.main()
