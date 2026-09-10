from dataclasses import dataclass
from typing import Optional

from lightcycle.application.setup.upgrade import RemoteVersionUnavailableError, upgrade


@dataclass(frozen=True)
class UpgradeNoticeResponse:
    notice: Optional[str]
    remote: Optional[str]
    error: Optional[str]


class UpgradeNoticeUseCase:
    def __init__(self, current_version, check=None, port=None):
        self._current_version = current_version
        self._check = check or (
            lambda: upgrade(current_version, check_only=True, fetch=port.fetch_remote_version)
        )

    def execute(self) -> UpgradeNoticeResponse:
        try:
            resp = self._check()
        except (OSError, ValueError, RemoteVersionUnavailableError) as e:
            return UpgradeNoticeResponse(notice=None, remote=None, error=str(e))
        if not resp.available:
            return UpgradeNoticeResponse(notice=None, remote=None, error=None)
        notice = "a newer lightcycle is available (%s -> %s); run lc upgrade" % (
            resp.current, resp.remote,
        )
        return UpgradeNoticeResponse(notice=notice, remote=resp.remote, error=None)
