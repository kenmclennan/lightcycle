import unittest
from unittest.mock import patch

from lightcycle.application.setup.upgrade import UpgradeResponse
from lightcycle.application.setup.upgrade_notice import UpgradeNoticeUseCase


class TestUpgradeNoticeUseCase(unittest.TestCase):
    def test_notice_and_remote_set_when_available(self):
        def fake_check():
            return UpgradeResponse(current="0.2.0", remote="0.3.0", available=True, applied=False)

        resp = UpgradeNoticeUseCase("0.2.0", check=fake_check).execute()

        self.assertEqual(resp.notice, "a newer lightcycle is available (0.2.0 -> 0.3.0); run lc upgrade")
        self.assertEqual(resp.remote, "0.3.0")
        self.assertIsNone(resp.error)

    def test_nothing_set_when_already_latest(self):
        def fake_check():
            return UpgradeResponse(current="0.2.0", remote="0.2.0", available=False, applied=False)

        resp = UpgradeNoticeUseCase("0.2.0", check=fake_check).execute()

        self.assertIsNone(resp.notice)
        self.assertIsNone(resp.remote)
        self.assertIsNone(resp.error)

    def test_error_surfaced_when_check_raises(self):
        def raising_check():
            raise ValueError("boom")

        resp = UpgradeNoticeUseCase("0.2.0", check=raising_check).execute()

        self.assertIsNone(resp.notice)
        self.assertIsNone(resp.remote)
        self.assertEqual(resp.error, "boom")

    def test_default_check_calls_upgrade_with_the_given_current_version(self):
        with patch("lightcycle.application.setup.upgrade_notice.upgrade") as fake_upgrade:
            fake_upgrade.return_value = UpgradeResponse(
                current="0.2.0", remote="0.2.0", available=False, applied=False
            )

            UpgradeNoticeUseCase("0.2.0").execute()

            fake_upgrade.assert_called_once_with("0.2.0", check_only=True)


if __name__ == "__main__":
    unittest.main()
