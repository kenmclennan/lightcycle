"""BdStore port-contract subset: verifies real bd wiring for covered operations."""
import os
import subprocess
import tempfile
import unittest

from the_grid.adapters.store import BdStore
from tests.store_contract import StoreContractBase


def _new_bd_root():
    d = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(
        ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
        cwd=d, check=True,
    )
    return d


class TestBdStoreContract(StoreContractBase, unittest.TestCase):

    def setUp(self):
        self._root = _new_bd_root()
        self._prior_root = os.environ.get("GRID_ROOT_OVERRIDE")
        os.environ["GRID_ROOT_OVERRIDE"] = self._root

    def tearDown(self):
        if self._prior_root is None:
            os.environ.pop("GRID_ROOT_OVERRIDE", None)
        else:
            os.environ["GRID_ROOT_OVERRIDE"] = self._prior_root

    def make_store(self):
        return BdStore()


if __name__ == "__main__":
    unittest.main()
