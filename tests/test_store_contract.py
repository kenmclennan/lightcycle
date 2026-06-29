"""BdStore port-contract subset: verifies real bd wiring for covered operations."""
import os
import shutil
import subprocess
import tempfile
import unittest

from the_grid.adapters.store import BdStore
from the_grid.config import Config
from tests.store_contract import StoreContractBase

_TEMPLATE = None


def _template():
    """One real bd store inited per run; copied per test (full real-bd fidelity,
    without paying bd/Dolt init 14 times)."""
    global _TEMPLATE
    if _TEMPLATE is None:
        d = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(
            ["bd", "init", "--skip-agents", "--skip-hooks", "--non-interactive", "--quiet"],
            cwd=d, check=True,
        )
        _TEMPLATE = d
    return _TEMPLATE


def _new_bd_root():
    d = tempfile.mkdtemp()
    shutil.copytree(_template(), d, dirs_exist_ok=True)
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
        return BdStore(Config())


if __name__ == "__main__":
    unittest.main()
