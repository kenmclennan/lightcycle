"""InitGrid: create the grid store and seed the logs dir + HOME config."""


class InitGrid:

    def __init__(self, store, fs, config):
        self._store = store
        self._fs = fs
        self._config = config

    def execute(self):
        existed = self._fs.store_ready()
        self._store.ensure_beads()
        self._fs.ensure_logs_dir()
        created = self._config.ensure_config()
        return {"existed": existed, "created": created, "config_path": self._config.config_path()}
