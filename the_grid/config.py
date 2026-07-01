"""Config: the single boundary to the process environment and the config file.

Every value the engine reads from outside its own code passes through here - the
config file (key -> value) and the process environment (GRID_* tunables and the
spawn protocol). This is the ONLY module that reads os.environ.

Policy:
- projects/specs roots are REQUIRED: absent -> a clear error naming the key and
  the config path. `tg init` seeds them, so a configured engine is unaffected.
- every other value carries an EXPLICIT, documented default (the DEFAULT_*
  constants below) - there are no hidden fallbacks buried in call sites.
- a malformed numeric value fails fast naming the key, rather than silently
  reverting to its default.
"""
import os
from pathlib import Path

from the_grid.adapters import frontmatter


class ConfigError(Exception):
    """A required configuration value is missing, or a value is malformed."""


class Config:

    DEFAULT_BRANCH_PREFIX = "feat"
    DEFAULT_MAX_AGENTS = 4
    DEFAULT_WORKTREE_RETRIES = 6
    DEFAULT_WORKTREE_RETRY_SLEEP = 0.25
    DEFAULT_MAX_BOOT_SECONDS = 120
    DEFAULT_POLL_SECONDS = 5
    DEFAULT_WORKER_HISTORY = 20
    DEFAULT_EDITOR = "vi"

    def __init__(self, environ=None):
        self._environ = environ if environ is not None else os.environ

    # ---- environment helpers (the only os.environ reads in the codebase) ----

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
        """A mutable copy of the process environment, for propagation to child
        processes (bd, spawned workers). Callers add their own keys."""
        return dict(self._environ)

    # ---- the engine / data-store root (GRID_ROOT_OVERRIDE redirects the store) ----

    def grid_root(self):
        override = self._env("GRID_ROOT_OVERRIDE")
        if override:
            return override
        return str(Path(__file__).resolve().parents[1])

    # ---- config file ----

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
        return "projects: ~/workspace/projects\nspecs: ~/workspace/specs\n"

    def ensure_config(self):
        """Seed the default config file if absent. Returns True if it was created."""
        p = self.config_path()
        if os.path.exists(p):
            return False
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(self._default_config_text())
        return True

    # ---- value resolution ----

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
                % (key, key, self.config_path()))
        return self._expand(v)

    def projects_root(self):
        return self._required_path("projects")

    def specs_root(self):
        return self._required_path("specs")

    def branch_prefix(self):
        cfg = self.load_config()
        return cfg.get("branch-prefix") or cfg.get("branch_prefix") or self.DEFAULT_BRANCH_PREFIX

    def max_agents(self):
        env = self._env_int("GRID_MAX_AGENTS", None)
        if env is not None:
            return env
        raw = self.load_config().get("max-agents") or self.load_config().get("max_agents")
        if not raw:
            return self.DEFAULT_MAX_AGENTS
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ConfigError("config value 'max-agents' must be an integer (got %r)" % raw)

    def worktree_retries(self):
        return self._env_int("GRID_WORKTREE_RETRIES", self.DEFAULT_WORKTREE_RETRIES)

    def worktree_retry_sleep(self):
        return self._env_float("GRID_WORKTREE_RETRY_SLEEP", self.DEFAULT_WORKTREE_RETRY_SLEEP)

    def max_boot_seconds(self):
        return self._env_int("GRID_MAX_BOOT_SECONDS", self.DEFAULT_MAX_BOOT_SECONDS)

    def poll_seconds(self):
        return self._env_int("GRID_POLL_SECONDS", self.DEFAULT_POLL_SECONDS)

    def worker_history(self):
        return self._env_int("GRID_WORKER_HISTORY", self.DEFAULT_WORKER_HISTORY)

    def editor(self):
        return self._env("EDITOR") or self.DEFAULT_EDITOR

    # ---- the spawn protocol (set per child process by the spawner) ----

    def spawn_id(self):
        return self._env("GRID_SPAWNID")

    def spawn_cmd(self):
        return self._env("GRID_SPAWN_CMD")
