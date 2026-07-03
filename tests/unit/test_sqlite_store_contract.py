import unittest

from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.store_contract import StoreContractBase


class TestSqliteStoreContract(StoreContractBase, unittest.TestCase):
    def make_store(self):
        return make_sqlite_store()


if __name__ == "__main__":
    unittest.main()
