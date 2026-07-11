import unittest

from lightcycle.application.setup.upgrade import UpgradeResponse
from lightcycle.cli import _upgrade_notice


class TestUpgradeNotice(unittest.TestCase):
    def test_prints_notice_when_available(self):
        def fake_check():
            return UpgradeResponse(current="0.2.0", remote="0.3.0", available=True, applied=False)

        notice = _upgrade_notice(fake_check)
        self.assertEqual(notice, "a newer lightcycle is available (0.2.0 -> 0.3.0); run lc upgrade")

    def test_no_notice_when_not_available(self):
        def fake_check():
            return UpgradeResponse(current="0.2.0", remote="0.2.0", available=False, applied=False)

        self.assertIsNone(_upgrade_notice(fake_check))

    def test_no_notice_when_check_raises(self):
        def fake_check():
            raise ValueError("boom")

        self.assertIsNone(_upgrade_notice(fake_check))


if __name__ == "__main__":
    unittest.main()
