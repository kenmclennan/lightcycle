from dataclasses import dataclass


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
        return InitGridResponse(
            existed=existed, created=created, config_path=self._config.config_path()
        )
