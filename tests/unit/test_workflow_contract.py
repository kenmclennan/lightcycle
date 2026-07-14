import unittest

from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible


class TestEngineContract(unittest.TestCase):
    def test_engine_contract_is_one(self):
        self.assertEqual(ENGINE_CONTRACT, 1)

    def test_same_contract_is_compatible(self):
        self.assertTrue(contract_compatible(ENGINE_CONTRACT))

    def test_higher_source_contract_is_incompatible(self):
        self.assertFalse(contract_compatible(ENGINE_CONTRACT + 1))

    def test_lower_source_contract_is_incompatible(self):
        self.assertFalse(contract_compatible(ENGINE_CONTRACT - 1))


if __name__ == "__main__":
    unittest.main()
