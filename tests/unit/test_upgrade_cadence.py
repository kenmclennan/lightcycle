import unittest

from lightcycle.application.pool.upgrade_cadence import UpgradeCadenceUseCase
from lightcycle.application.setup.upgrade_notice import UpgradeNoticeResponse

_AVAILABLE_180 = UpgradeNoticeResponse(
    notice="a newer lightcycle is available (0.6.179 -> 0.6.180); run lc upgrade",
    remote="0.6.180",
    error=None,
)
_AVAILABLE_181 = UpgradeNoticeResponse(
    notice="a newer lightcycle is available (0.6.179 -> 0.6.181); run lc upgrade",
    remote="0.6.181",
    error=None,
)
_NOT_AVAILABLE = UpgradeNoticeResponse(notice=None, remote=None, error=None)
_ERROR = UpgradeNoticeResponse(notice=None, remote=None, error="boom")


class FakeNotice:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def execute(self):
        self.calls += 1
        return self._responses.pop(0)


class TestUpgradeCadenceUseCase(unittest.TestCase):
    def test_the_first_call_is_always_due_regardless_of_now(self):
        notice = FakeNotice([_AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)

        resp = cadence.execute(now=123456.0)

        self.assertEqual(resp.remote, "0.6.180")
        self.assertEqual(notice.calls, 1)

    def test_a_call_before_the_interval_has_elapsed_returns_empty_and_does_not_check(self):
        notice = FakeNotice([_AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)
        cadence.execute(now=0)

        resp = cadence.execute(now=899)

        self.assertIsNone(resp.notice)
        self.assertIsNone(resp.remote)
        self.assertIsNone(resp.error)
        self.assertEqual(notice.calls, 1)

    def test_a_call_at_or_after_the_interval_rechecks(self):
        notice = FakeNotice([_AVAILABLE_180, _AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)
        cadence.execute(now=0)

        cadence.execute(now=900)

        self.assertEqual(notice.calls, 2)

    def test_an_available_notice_prints_once_then_is_suppressed_for_the_same_remote(self):
        notice = FakeNotice([_AVAILABLE_180, _AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)

        first = cadence.execute(now=0)
        second = cadence.execute(now=900)

        self.assertEqual(first.remote, "0.6.180")
        self.assertIsNone(second.notice)
        self.assertIsNone(second.remote)

    def test_an_available_notice_for_a_further_advanced_remote_prints_again(self):
        notice = FakeNotice([_AVAILABLE_180, _AVAILABLE_180, _AVAILABLE_181])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)
        cadence.execute(now=0)
        cadence.execute(now=900)

        third = cadence.execute(now=1800)

        self.assertEqual(third.remote, "0.6.181")

    def test_an_error_prints_once_then_is_suppressed_for_the_same_streak(self):
        notice = FakeNotice([_ERROR, _ERROR])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)

        first = cadence.execute(now=0)
        second = cadence.execute(now=900)

        self.assertEqual(first.error, "boom")
        self.assertIsNone(second.notice)
        self.assertIsNone(second.error)

    def test_a_successful_check_after_an_error_streak_clears_it_so_a_later_error_prints_again(self):
        notice = FakeNotice([_ERROR, _NOT_AVAILABLE, _ERROR])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)
        cadence.execute(now=0)
        cadence.execute(now=900)

        third = cadence.execute(now=1800)

        self.assertEqual(third.error, "boom")

    def test_an_error_tick_does_not_clobber_a_known_available_version(self):
        notice = FakeNotice([_AVAILABLE_180, _ERROR, _AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=900)
        cadence.execute(now=0)

        error_tick = cadence.execute(now=900)
        recovered = cadence.execute(now=1800)

        self.assertEqual(error_tick.error, "boom")
        self.assertIsNone(recovered.notice)
        self.assertIsNone(recovered.remote)

    def test_interval_zero_the_first_check_still_runs_but_no_later_call_is_ever_due(self):
        notice = FakeNotice([_AVAILABLE_180])
        cadence = UpgradeCadenceUseCase(notice, interval_seconds=0)

        first = cadence.execute(now=0)
        second = cadence.execute(now=1_000_000)

        self.assertEqual(first.remote, "0.6.180")
        self.assertIsNone(second.notice)
        self.assertEqual(notice.calls, 1)
