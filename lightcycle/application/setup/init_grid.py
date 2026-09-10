from dataclasses import dataclass

from lightcycle.domain.flow.flow import SPECS_WORKSPACE

_DEFAULT_SPECS_PATH = "~/workspace/specs"


@dataclass(frozen=True)
class InitGridResponse:
    existed: bool
    created: bool
    config_path: str


class InitGridUseCase:
    def __init__(self, store, fs, config):
        self._store = store
        self._fs = fs
        self._config = config

    def execute(self) -> InitGridResponse:
        existed = self._fs.store_ready()
        self._store.ensure_store()
        self._fs.ensure_logs_dir()
        created = self._config.ensure_config()
        self._ensure_specs_project()
        return InitGridResponse(
            existed=existed, created=created, config_path=self._config.config_path()
        )

    def _ensure_specs_project(self):
        if self._store.get_project(SPECS_WORKSPACE) is not None:
            return
        legacy = self._config.load_config()
        legacy_path = legacy.get("specs")
        if legacy_path:
            path = self._config.expand_path(legacy_path)
            remote = legacy.get("specs-remote") or None
        else:
            path = self._config.expand_path(_DEFAULT_SPECS_PATH)
            remote = None
        self._store.add_project(SPECS_WORKSPACE, local_path=path, remote=remote)
