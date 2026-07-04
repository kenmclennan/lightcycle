import os
from pathlib import Path

from the_grid.adapters import frontmatter


_SEED_KEYS = [
    ("projects", "~/workspace/projects"),
    ("specs", "~/workspace/specs"),
    ("branch-prefix", "feat"),
    ("shortcode", "PROJ"),
    ("max-agents", "5"),
    ("worktree-retries", "6"),
    ("worktree-retry-sleep", "0.25"),
    ("max-boot-seconds", "120"),
    ("max-session-seconds", "1800"),
    ("poll-seconds", "5"),
    ("worker-history", "20"),
    ("editor", "vi"),
    ("retro-interval-days", "7"),
    ("retro-min-epics", "3"),
]


class ConfigError(Exception):
    pass


class Config:

    def __init__(self, environ=None):
        self._environ = environ if environ is not None else os.environ

    def _env(self, key):
        v = self._environ.get(key)
        return v if v else None

    def _env_int(self, key, default):
        raw = self._env(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            raise ConfigError("%s must be an integer (got %r)" % (key, raw))

    def _env_float(self, key, default):
        raw = self._env(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            raise ConfigError("%s must be a number (got %r)" % (key, raw))

    def base_env(self):
        return dict(self._environ)

    def grid_root(self):
        override = self._env("GRID_ROOT_OVERRIDE")
        if override:
            return override
        return str(Path(__file__).resolve().parents[1])

    def config_path(self):
        override = self._env("GRID_CONFIG")
        if override:
            return override
        base = self._env("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "the-grid", "config")

    def load_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return frontmatter.parse_frontmatter(f.read())

    def _default_config_text(self):
        return "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS)

    def ensure_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(self._default_config_text())
            return True
        existing = self.load_config()
        missing = [(k, v) for k, v in _SEED_KEYS if k not in existing]
        if not missing:
            return False
        with open(p, "a") as f:
            for k, v in missing:
                f.write("%s: %s\n" % (k, v))
        return True

    def _home(self):
        return os.path.expanduser("~")

    def _expand(self, v):
        home = self._home()
        if v == "~":
            return home
        if v.startswith("~/"):
            v = os.path.join(home, v[2:])
        return v if os.path.isabs(v) else os.path.join(home, v)

    def _required_path(self, key):
        v = self.load_config().get(key)
        if not v:
            raise ConfigError(
                "required config value %r is not set. Add `%s: <path>` to %s "
                "(or run `tg init`), or point GRID_CONFIG at a config that sets it."
                % (key, key, self.config_path())
            )
        return self._expand(v)

    def _required_int(self, key):
        v = self.load_config().get(key)
        if not v:
            raise ConfigError(
                "required config value %r is not set. Add `%s: <value>` to %s "
                "(or run `tg init`)."
                % (key, key, self.config_path()))
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ConfigError("config value %r must be an integer (got %r)" % (key, v))

    def _required_float(self, key):
        v = self.load_config().get(key)
        if not v:
            raise ConfigError(
                "required config value %r is not set. Add `%s: <value>` to %s "
                "(or run `tg init`)."
                % (key, key, self.config_path()))
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ConfigError("config value %r must be a number (got %r)" % (key, v))

    def _required_str(self, key):
        v = self.load_config().get(key)
        if not v:
            raise ConfigError(
                "required config value %r is not set. Add `%s: <value>` to %s "
                "(or run `tg init`)."
                % (key, key, self.config_path()))
        return str(v)

    def projects_root(self):
        return self._required_path("projects")

    def specs_root(self):
        return self._required_path("specs")

    def branch_prefix(self):
        return self._required_str("branch-prefix")

    def shortcode(self):
        return self._required_str("shortcode")

    def max_agents(self):
        env = self._env_int("GRID_MAX_AGENTS", None)
        if env is not None:
            return env
        return self._required_int("max-agents")

    def worktree_retries(self):
        env = self._env_int("GRID_WORKTREE_RETRIES", None)
        if env is not None:
            return env
        return self._required_int("worktree-retries")

    def worktree_retry_sleep(self):
        env = self._env_float("GRID_WORKTREE_RETRY_SLEEP", None)
        if env is not None:
            return env
        return self._required_float("worktree-retry-sleep")

    def max_boot_seconds(self):
        env = self._env_int("GRID_MAX_BOOT_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("max-boot-seconds")

    def max_session_seconds(self):
        env = self._env_int("GRID_MAX_SESSION_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("max-session-seconds")

    def poll_seconds(self):
        env = self._env_int("GRID_POLL_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("poll-seconds")

    def worker_history(self):
        env = self._env_int("GRID_WORKER_HISTORY", None)
        if env is not None:
            return env
        return self._required_int("worker-history")

    def editor(self):
        raw = self._env("EDITOR")
        if raw:
            return raw
        return self._required_str("editor")

    def retro_interval_days(self):
        env = self._env_int("GRID_RETRO_INTERVAL_DAYS", None)
        if env is not None:
            return env
        return self._required_int("retro-interval-days")

    def retro_min_epics(self):
        env = self._env_int("GRID_RETRO_MIN_EPICS", None)
        if env is not None:
            return env
        return self._required_int("retro-min-epics")

    def spawn_id(self):
        return self._env("GRID_SPAWNID")

    def spawn_cmd(self):
        return self._env("GRID_SPAWN_CMD")
