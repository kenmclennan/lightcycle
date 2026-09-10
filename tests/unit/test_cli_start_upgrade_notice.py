import unittest

from lightcycle.application.setup.upgrade import UpgradeResponse
from lightcycle.application.setup.upgrade_notice import UpgradeNoticeUseCase
from lightcycle.cli import _upgrade_notice_lines


class TestUpgradeNoticeLines(unittest.TestCase):
    def test_prints_notice_when_available(self):
        resp = UpgradeNoticeUseCase(
            "0.2.0",
            check=lambda: UpgradeResponse(current="0.2.0", remote="0.3.0", available=True, applied=False),
        ).execute()

        self.assertEqual(
            _upgrade_notice_lines(resp),
            ["a newer lightcycle is available (0.2.0 -> 0.3.0); run lc upgrade"],
        )

    def test_no_lines_when_not_available(self):
        resp = UpgradeNoticeUseCase(
            "0.2.0",
            check=lambda: UpgradeResponse(current="0.2.0", remote="0.2.0", available=False, applied=False),
        ).execute()

        self.assertEqual(_upgrade_notice_lines(resp), [])

    def test_renders_the_failure_reason_when_check_raises(self):
        def raising_check():
            raise ValueError("boom")

        resp = UpgradeNoticeUseCase("0.2.0", check=raising_check).execute()

        self.assertEqual(_upgrade_notice_lines(resp), ["could not check for updates: boom"])


if __name__ == "__main__":
    unittest.main()
