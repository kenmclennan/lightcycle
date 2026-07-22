import os
from pathlib import Path

from lightcycle.adapters import frontmatter


_SEED_KEYS = [
    ("projects", "~/workspace/projects"),
    ("specs", "~/workspace/specs"),
    ("specs-remote", "git@github.com:you/lightcycle-specs.git"),
    ("branch-prefix", "feat"),
    ("shortcode", "PROJ"),
    ("default-origin", "lightcycle"),
    ("workflows-remote", "git@github.com:kenmclennan/lightcycle-workflows.git"),
    ("max-agents", "5"),
    ("worktree-retries", "6"),
    ("worktree-retry-sleep", "0.25"),
    ("max-boot-seconds", "120"),
    ("max-session-seconds", "1800"),
    ("poll-seconds", "5"),
    ("worker-history", "20"),
    ("editor", "vi"),
    ("retro-interval-reflections", "20"),
    ("backups-dir", "~/.lightcycle-backups"),
    ("backup-interval-minutes", "15"),
    ("backup-retention", "96"),
    ("workflow-retention", "5"),
    ("max-title-length", "72"),
    ("personal-origin", ""),
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

    def _engine_root(self):
        return str(Path(__file__).resolve().parents[1])

    def engine_root(self):
        return self._engine_root()

    def package_root(self):
        return self._engine_root()

    def prompts_root(self):
        return str(Path(__file__).resolve().parent / "prompts")

    def data_root(self):
        override = self._env("LC_HOME")
        if override:
            return override
        return self.default_data_root()

    def default_data_root(self):
        return os.path.join(self._home(), ".lightcycle")

    def is_live_home(self):
        return os.path.normpath(self.data_root()) == os.path.normpath(
            self.default_data_root()
        )

    def config_path(self):
        override = self._env("LC_CONFIG")
        if override:
            return override
        return os.path.join(self.data_root(), "config")

    def load_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return frontmatter.parse_frontmatter(f.read())

    def _default_config_text(self):
        return "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS)

    def _missing_seed_keys(self, existing):
        return [(k, v) for k, v in _SEED_KEYS if k not in existing]

    def reconcile_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            return ()
        missing = self._missing_seed_keys(self.load_config())
        if not missing:
            return ()
        with open(p, "a") as f:
            for k, v in missing:
                f.write("%s: %s\n" % (k, v))
        return tuple(k for k, v in missing)

    def missing_config_keys(self):
        return tuple(k for k, v in self._missing_seed_keys(self.load_config()))

    def ensure_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(self._default_config_text())
            return True
        return bool(self.reconcile_config())

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
                "(or run `lc init`), or point LC_CONFIG at a config that sets it."
                % (key, key, self.config_path())
            )
        return self._expand(v)

    def _required_int(self, key):
        v = self.load_config().get(key)
        if not v:
            raise ConfigError(
                "required config value %r is not set. Add `%s: <value>` to %s "
                "(or run `lc init`)."
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
                "(or run `lc init`)."
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
                "(or run `lc init`)."
                % (key, key, self.config_path()))
        return str(v)

    def projects_root(self):
        return self._required_path("projects")

    def specs_root(self):
        return self._required_path("specs")

    def specs_remote(self):
        return self._required_str("specs-remote")

    def branch_prefix(self):
        return self._required_str("branch-prefix")

    def shortcode(self):
        return self._required_str("shortcode")

    def default_origin(self):
        return self._required_str("default-origin")

    def workflows_remote(self):
        return self._required_str("workflows-remote")

    def project_config(self, project):
        if not project:
            return {}
        p = os.path.join(self.projects_root(), project, ".lightcycle", "config")
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return frontmatter.parse_frontmatter(f.read())

    def shortcode_for(self, project):
        return self.project_config(project).get("shortcode") or self.shortcode()

    def max_agents(self):
        env = self._env_int("LC_MAX_AGENTS", None)
        if env is not None:
            return env
        return self._required_int("max-agents")

    def worktree_retries(self):
        env = self._env_int("LC_WORKTREE_RETRIES", None)
        if env is not None:
            return env
        return self._required_int("worktree-retries")

    def worktree_retry_sleep(self):
        env = self._env_float("LC_WORKTREE_RETRY_SLEEP", None)
        if env is not None:
            return env
        return self._required_float("worktree-retry-sleep")

    def max_boot_seconds(self):
        env = self._env_int("LC_MAX_BOOT_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("max-boot-seconds")

    def max_session_seconds(self):
        env = self._env_int("LC_MAX_SESSION_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("max-session-seconds")

    def poll_seconds(self):
        env = self._env_int("LC_POLL_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("poll-seconds")

    def worker_history(self):
        env = self._env_int("LC_WORKER_HISTORY", None)
        if env is not None:
            return env
        return self._required_int("worker-history")

    def editor(self):
        raw = self._env("EDITOR")
        if raw:
            return raw
        return self._required_str("editor")

    def retro_interval_reflections(self):
        env = self._env_int("LC_RETRO_INTERVAL_REFLECTIONS", None)
        if env is not None:
            return env
        return self._required_int("retro-interval-reflections")

    def backups_dir(self):
        return self._required_path("backups-dir")

    def backup_interval_minutes(self):
        return self._required_int("backup-interval-minutes")

    def backup_retention(self):
        return self._required_int("backup-retention")

    def workflow_retention(self):
        return self._required_int("workflow-retention")

    def max_title_length(self):
        return self._required_int("max-title-length")

    def personal_origin(self):
        v = self.load_config().get("personal-origin")
        return v or None

    def set_personal_origin(self, name):
        p = self.config_path()
        lines = []
        if os.path.exists(p):
            with open(p) as f:
                lines = f.readlines()
        for i, line in enumerate(lines):
            if line.split(":", 1)[0].strip() == "personal-origin":
                lines[i] = "personal-origin: %s\n" % name
                break
        else:
            lines.append("personal-origin: %s\n" % name)
        with open(p, "w") as f:
            f.writelines(lines)

    def spawn_id(self):
        return self._env("LC_SPAWNID")

    def is_worker(self):
        return bool(self._env("LC_WORKER"))

    def spawn_cmd(self):
        return self._env("LC_SPAWN_CMD")
