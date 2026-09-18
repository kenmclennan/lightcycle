from lightcycle.application.setup.upgrade_notice import UpgradeNoticeResponse

_EMPTY = UpgradeNoticeResponse(notice=None, remote=None, error=None)


class UpgradeCadenceUseCase:
    def __init__(self, notice, interval_seconds):
        self._notice = notice
        self._interval = interval_seconds
        self._last_checked_at = None
        self._last_notified_remote = None
        self._had_error = False

    def execute(self, now) -> UpgradeNoticeResponse:
        if not self._due(now):
            return _EMPTY
        self._last_checked_at = now
        resp = self._notice.execute()
        if resp.notice is not None:
            self._had_error = False
            if resp.remote == self._last_notified_remote:
                return _EMPTY
            self._last_notified_remote = resp.remote
            return resp
        if resp.error is not None:
            if self._had_error:
                return _EMPTY
            self._had_error = True
            return resp
        self._had_error = False
        self._last_notified_remote = None
        return resp

    def _due(self, now):
        if self._last_checked_at is None:
            return True
        if self._interval <= 0:
            return False
        return now - self._last_checked_at >= self._interval
