from dataclasses import dataclass

from lightcycle.domain.flow.flow import GUIDANCE_WORKSPACE
from lightcycle.domain.pool import GuidanceSyncState
from lightcycle.ports.git import GitOutcome, GitReadError


@dataclass(frozen=True)
class GuidanceSyncResponse:
    fetched: bool = False
    ok: bool = True
    detail: str = ""


class GuidanceSyncUseCase:
    def __init__(self, store, git, fs, status, config):
        self._store = store
        self._git = git
        self._fs = fs
        self._status = status
        self._config = config

    def _has_origin(self, root):
        try:
            return self._git.remote_url(root) is not None
        except GitReadError:
            return False

    def _due(self, now):
        last = self._status.load()
        if last is None or last.at is None:
            return True
        return now - last.at >= self._config.guidance_fetch_minutes() * 60

    def execute(self, now) -> GuidanceSyncResponse:
        project = self._store.get_project(GUIDANCE_WORKSPACE)
        if project is None or not project.local_path:
            return GuidanceSyncResponse()
        root = project.local_path
        if not self._fs.exists(root) or not self._has_origin(root):
            return GuidanceSyncResponse()
        if not self._due(now):
            return GuidanceSyncResponse()
        try:
            outcome = self._git.fetch_origin(root)
            ref = self._git.default_ref(root) if outcome.ok else None
        except GitReadError as e:
            outcome, ref = GitOutcome(ok=False, detail=str(e)), None
        self._status.save(
            GuidanceSyncState(ok=outcome.ok, at=now, detail=outcome.detail, ref=ref))
        return GuidanceSyncResponse(fetched=True, ok=outcome.ok, detail=outcome.detail)
