import unittest

from tests.support.fake_fs import FakeFs
from tests.support.fs_contract import FsContractBase


class TestFakeFsContract(FsContractBase, unittest.TestCase):
    def root(self):
        return "/root"

    def path(self, relpath):
        return relpath

    def make_fs(self, files=None, dirs=None, metas=None, bodies=None, workflows=None):
        return FakeFs(
            metas=metas,
            files=files,
            dirs=dirs,
            bodies=bodies,
            workflows=workflows,
            store_ready="store.db" in (files or {}),
        )


if __name__ == "__main__":
    unittest.main()
