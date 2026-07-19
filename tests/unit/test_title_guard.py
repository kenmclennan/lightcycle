import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.title_guard import validate_title


class FakeConfig:
    def __init__(self, cap=72):
        self._cap = cap

    def max_title_length(self):
        return self._cap


class TestValidateTitle(unittest.TestCase):
    def test_title_at_cap_is_accepted(self):
        validate_title(FakeConfig(cap=10), "x" * 10)

    def test_title_one_over_cap_is_rejected(self):
        with self.assertRaises(UseCaseError) as ctx:
            validate_title(FakeConfig(cap=10), "x" * 11)
        msg = str(ctx.exception)
        self.assertIn("10", msg)
        self.assertIn("--description", msg)

    def test_empty_or_none_title_is_accepted(self):
        validate_title(FakeConfig(cap=10), "")
        validate_title(FakeConfig(cap=10), None)


if __name__ == "__main__":
    unittest.main()
