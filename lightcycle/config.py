import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lightcycle import frontmatter
from lightcycle.domain.pool import ModelRates


_GETTER_NAME_OVERRIDES = {
    "projects": "projects_root",
}

_ENV_OVERRIDE_VARS = {
    "max-agents": "LC_MAX_AGENTS",
    "worktree-retries": "LC_WORKTREE_RETRIES",
    "worktree-retry-sleep": "LC_WORKTREE_RETRY_SLEEP",
    "max-boot-seconds": "LC_MAX_BOOT_SECONDS",
    "max-session-seconds": "LC_MAX_SESSION_SECONDS",
    "stall-seconds": "LC_STALL_SECONDS",
    "probe-cooldown-seconds": "LC_PROBE_COOLDOWN_SECONDS",
    "spin-cap": "LC_SPIN_CAP",
    "poll-seconds": "LC_POLL_SECONDS",
    "worker-history": "LC_WORKER_HISTORY",
    "editor": "EDITOR",
    "tui-autostart-pool": "LC_TUI_AUTOSTART_POOL",
    "tui-metrics": "LC_TUI_METRICS",
    "developer-mode": "LC_DEVELOPER_MODE",
    "tui-upgrade-check-seconds": "LC_TUI_UPGRADE_CHECK_SECONDS",
    "pool-upgrade-check-seconds": "LC_POOL_UPGRADE_CHECK_SECONDS",
    "shutdown-grace-seconds": "LC_SHUTDOWN_GRACE_SECONDS",
    "tick-failure-cap": "LC_TICK_FAILURE_CAP",
    "review-rounds-cap": "LC_REVIEW_ROUNDS_CAP",
    "audit-shortcode": "LC_AUDIT_SHORTCODE",
    "held-comment-shortcode": "LC_HELD_COMMENT_SHORTCODE",
    "memory-reserve-fraction": "LC_MEMORY_RESERVE_FRACTION",
    "guidance-budget-bytes": "LC_GUIDANCE_BUDGET_BYTES",
    "guidance-unused-after-deliveries": "LC_GUIDANCE_UNUSED_AFTER_DELIVERIES",
    "guidance-dormant-days": "LC_GUIDANCE_DORMANT_DAYS",
}

SCHEDULE_KEY_PREFIX = "schedule-"
WORKFLOW_KEY_PREFIX = "workflow-"

_TRUE = ("true", "yes", "1", "on")
_FALSE = ("false", "no", "0", "off")

_BLANK = (None, "", {})

RESTART_REQUIRED_KEYS = ("poll-seconds", "pool-upgrade-check-seconds", "tick-failure-cap", "spin-cap")

RELOAD_UNCHANGED = "unchanged"
RELOAD_RELOADED = "reloaded"
RELOAD_REJECTED = "rejected"


@dataclass(frozen=True)
class ConfigReloadResult:
    outcome: str
    reason: Optional[str] = None
    mtime: Optional[int] = None
    restart_required: tuple = ()


@dataclass(frozen=True)
class ResolvedSetting:
    key: str
    value: object
    error: Optional[str]
    state: str
    env_var: Optional[str]
    seed: Optional[str]


_SEED_KEYS = [
    ("projects", "~/workspace/projects"),
    ("branch-prefix", "feat"),
    ("default-origin", "lightcycle"),
    ("workflows-remote", ""),
    ("max-agents", "5"),
    ("worktree-retries", "6"),
    ("worktree-retry-sleep", "0.25"),
    ("max-boot-seconds", "120"),
    ("max-session-seconds", "1800"),
    ("stall-seconds", "1800"),
    ("probe-cooldown-seconds", "1800"),
    ("spin-cap", "3"),
    ("poll-seconds", "5"),
    ("worker-history", "20"),
    ("editor", "vi"),
    ("backups-dir", "~/.lightcycle-backups"),
    ("backup-interval-minutes", "15"),
    ("guidance-fetch-minutes", "5"),
    ("backup-retention", "96"),
    ("workflow-retention", "5"),
    ("max-title-length", "72"),
    ("tui-autostart-pool", "false"),
    ("tui-metrics", "false"),
    ("developer-mode", "false"),
    ("tui-upgrade-check-seconds", "900"),
    ("pool-upgrade-check-seconds", "900"),
    ("personal-origin", ""),
    ("price-sonnet-input-per-mtok", "2.00"),
    ("price-sonnet-output-per-mtok", "10.00"),
    ("price-sonnet-cache-write-per-mtok", "2.50"),
    ("price-sonnet-cache-read-per-mtok", "0.20"),
    ("price-opus-input-per-mtok", "5.00"),
    ("price-opus-output-per-mtok", "25.00"),
    ("price-opus-cache-write-per-mtok", "6.25"),
    ("price-opus-cache-read-per-mtok", "0.50"),
    ("price-haiku-input-per-mtok", "1.00"),
    ("price-haiku-output-per-mtok", "5.00"),
    ("price-haiku-cache-write-per-mtok", "1.25"),
    ("price-haiku-cache-read-per-mtok", "0.10"),
    ("shutdown-grace-seconds", "10"),
    ("tick-failure-cap", "5"),
    ("review-rounds-cap", "5"),
    ("context-artifact-types", "spec"),
    ("audit-shortcode", "AUD"),
    ("held-comment-shortcode", "HLD"),
    ("trusted-authors", ""),
    ("memory-reserve-fraction", "0.65"),
    ("guidance-budget-bytes", "6144"),
    ("guidance-unused-after-deliveries", "60"),
    ("guidance-dormant-days", "60"),
    ("schedules-paused", "false"),
    ("lifecycle-timeout-seconds", "300"),
    ("script-timeout-seconds", "300"),
    ("script-max-running", "4"),
]

_SEED_SCHEDULES = """\
schedule-retro-audit:
  enabled: true
  workflow: lightcycle/retro-audit
  project: guidance
  shortcode: AUD
  cron: 0 9 * * *
  guard: pending-reflections
  min: 30
schedule-material-audit:
  enabled: true
  workflow: lightcycle/material-audit
  project: guidance
  shortcode: AUD
  cron: 0 9 * * 1
  guard: materials-changed
schedule-daily-summary:
  enabled: true
  workflow: lightcycle/daily-summary
  project: guidance
  shortcode: SUM
  cron: 0 7 * * *
  guard: day-unsummarised
"""

_NUMERIC_RANGES = {
    "memory-reserve-fraction": (0.0, 1.0),
    "max-agents": (0, None),
    "guidance-budget-bytes": (0, None),
    "guidance-unused-after-deliveries": (1, None),
    "guidance-dormant-days": (1, None),
    "lifecycle-timeout-seconds": (1, None),
    "script-timeout-seconds": (1, None),
    "script-max-running": (1, None),
    "workflow-retention": (1, None),
    "max-boot-seconds": (0, None),
    "max-session-seconds": (0, None),
    "stall-seconds": (0, None),
    "probe-cooldown-seconds": (0, None),
    "tui-upgrade-check-seconds": (0, None),
    "pool-upgrade-check-seconds": (0, None),
    "shutdown-grace-seconds": (0, None),
    "price-sonnet-input-per-mtok": (0.0, None),
    "price-sonnet-output-per-mtok": (0.0, None),
    "price-sonnet-cache-write-per-mtok": (0.0, None),
    "price-sonnet-cache-read-per-mtok": (0.0, None),
    "price-opus-input-per-mtok": (0.0, None),
    "price-opus-output-per-mtok": (0.0, None),
    "price-opus-cache-write-per-mtok": (0.0, None),
    "price-opus-cache-read-per-mtok": (0.0, None),
    "price-haiku-input-per-mtok": (0.0, None),
    "price-haiku-output-per-mtok": (0.0, None),
    "price-haiku-cache-write-per-mtok": (0.0, None),
    "price-haiku-cache-read-per-mtok": (0.0, None),
}


class ConfigError(Exception):
    pass


class ConfigValueError(ConfigError):
    pass


class Config:

    def __init__(self, environ=None):
        self._environ = environ if environ is not None else os.environ
        self._cached = None
        self._cached_path = None
        self._loaded_mtime = None
        self._rejected = None

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
            raise ConfigValueError("%s must be an integer (got %r)" % (key, raw))

    def _env_bool(self, key, default):
        raw = self._env(key)
        if raw is None:
            return default
        return self._parse_bool(key, raw)

    def _env_float(self, key, default):
        raw = self._env(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            raise ConfigValueError("%s must be a number (got %r)" % (key, raw))

    def base_env(self):
        return dict(self._environ)

    def agent_env(self):
        env = self.base_env()
        pin = os.path.realpath(self.engine_root())
        kept = [
            e for e in env.get("PYTHONPATH", "").split(os.pathsep)
            if e and os.path.realpath(e) != pin
        ]
        if kept:
            env["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            env.pop("PYTHONPATH", None)
        return env

    def _engine_root(self):
        return str(Path(__file__).resolve().parents[1])

    def engine_root(self):
        return self._engine_root()

    def package_root(self):
        return self._engine_root()

    def prompts_root(self):
        return str(Path(__file__).resolve().parent / "prompts")

    def version(self):
        from lightcycle import __version__

        return __version__

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
        if self._cached is not None and self._cached_path == p:
            return self._cached
        self._cached_path = p
        self._loaded_mtime = self.config_mtime()
        self._rejected = None
        self._cached = self._read_config(p)
        return self._cached

    def _read_config(self, p):
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return frontmatter.parse_frontmatter(f.read())

    def config_mtime(self):
        try:
            return os.stat(self.config_path()).st_mtime_ns
        except OSError:
            return None

    def reload(self):
        self._cached = None
        self._cached_path = None
        self._loaded_mtime = None
        self._rejected = None

    def raw_values(self, keys):
        loaded = self.load_config()
        return {k: loaded.get(k) for k in keys}

    def try_reload(self, start_values=None):
        mtime = self.config_mtime()
        if self._cached is not None and mtime == self._loaded_mtime:
            return ConfigReloadResult(RELOAD_UNCHANGED, mtime=mtime)
        if self._rejected is not None and self._rejected == (mtime,):
            return ConfigReloadResult(RELOAD_UNCHANGED, mtime=mtime)
        if self._cached is None:
            self.load_config()
            return ConfigReloadResult(RELOAD_UNCHANGED, mtime=self._loaded_mtime)
        if mtime is None:
            return self._reject(mtime, "config file is missing")
        try:
            candidate = self._read_config(self.config_path())
        except (OSError, UnicodeDecodeError) as e:
            return self._reject(mtime, "config file could not be read: %s" % e)
        previous = (self._cached, self._cached_path, self._loaded_mtime)
        unset_before = {s.key for s in self.resolved_settings() if s.state == "unset"}
        self._cached, self._cached_path, self._loaded_mtime = (
            candidate, self.config_path(), mtime)
        bad = [
            s for s in self.resolved_settings()
            if s.state == "invalid" or (s.state == "unset" and s.key not in unset_before)
        ]
        if bad:
            self._cached, self._cached_path, self._loaded_mtime = previous
            reason = bad[0].error
            if len(bad) > 1:
                reason = "%s (and %d more)" % (reason, len(bad) - 1)
            return self._reject(mtime, reason)
        self._rejected = None
        return ConfigReloadResult(
            RELOAD_RELOADED, mtime=mtime,
            restart_required=self._restart_required(candidate, start_values or {}))

    def _reject(self, mtime, reason):
        self._rejected = (mtime,)
        return ConfigReloadResult(RELOAD_REJECTED, reason=reason, mtime=mtime)

    def _restart_required(self, candidate, start_values):
        return tuple(
            k for k in RESTART_REQUIRED_KEYS
            if k in start_values
            and self._env(_ENV_OVERRIDE_VARS[k]) is None
            and candidate.get(k) != start_values[k]
        )

    def _default_config_text(self):
        return "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS) + _SEED_SCHEDULES

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
        self.reload()
        return tuple(k for k, v in missing)

    def missing_config_keys(self):
        return tuple(k for k, v in self._missing_seed_keys(self.load_config()))

    def obsolete_config_keys(self):
        seed_names = {k for k, v in _SEED_KEYS}
        return tuple(
            k for k, v in self.load_config().items()
            if k not in seed_names and not k.startswith(SCHEDULE_KEY_PREFIX)
            and not (k.startswith(WORKFLOW_KEY_PREFIX) and isinstance(v, dict)))

    def resolved_settings(self):
        entries = []
        for key, default in _SEED_KEYS:
            getter = getattr(self, _GETTER_NAME_OVERRIDES.get(key, key.replace("-", "_")))
            try:
                value = getter()
            except ConfigValueError as e:
                entries.append(ResolvedSetting(
                    key=key, value=None, error=str(e), state="invalid", env_var=None, seed=default))
                continue
            except ConfigError as e:
                entries.append(ResolvedSetting(
                    key=key, value=None, error=str(e), state="unset", env_var=None, seed=default))
                continue
            env_var = _ENV_OVERRIDE_VARS.get(key)
            if env_var and self._env(env_var) is not None:
                entries.append(ResolvedSetting(
                    key=key, value=value, error=None, state="env", env_var=env_var, seed=default))
                continue
            entries.append(ResolvedSetting(
                key=key, value=value, error=None, state="set", env_var=None, seed=default))
        return entries

    def ensure_config(self):
        p = self.config_path()
        if not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(self._default_config_text())
            self.reload()
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

    def expand_path(self, v):
        return self._expand(v)

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
            raise ConfigValueError("config value %r must be an integer (got %r)" % (key, v))

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
            raise ConfigValueError("config value %r must be a number (got %r)" % (key, v))

    def _check_range(self, key, value):
        bounds = _NUMERIC_RANGES.get(key)
        if bounds is None:
            return value
        lo, hi = bounds
        if lo is not None and value < lo:
            raise ConfigValueError("config value %r must be >= %r (got %r)" % (key, lo, value))
        if hi is not None and value > hi:
            raise ConfigValueError("config value %r must be <= %r (got %r)" % (key, hi, value))
        return value

    @staticmethod
    def _parse_bool(key, raw):
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ConfigValueError(
            "config value %r must be one of %s or %s (got %r)"
            % (key, "/".join(_TRUE), "/".join(_FALSE), raw))

    def _required_bool(self, key):
        v = self.load_config().get(key)
        if v in _BLANK:
            raise ConfigError(
                "required config value %r is not set. Add `%s: true` or `%s: false` to %s "
                "(or run `lc init`)."
                % (key, key, key, self.config_path()))
        return self._parse_bool(key, v)

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

    def branch_prefix(self):
        return self._required_str("branch-prefix")

    def default_origin(self):
        return self._required_str("default-origin")

    def workflows_remote(self):
        return self._required_str("workflows-remote")

    def max_agents(self):
        env = self._env_int("LC_MAX_AGENTS", None)
        value = env if env is not None else self._required_int("max-agents")
        return self._check_range("max-agents", value)

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
        value = env if env is not None else self._required_int("max-boot-seconds")
        return self._check_range("max-boot-seconds", value)

    def max_session_seconds(self):
        env = self._env_int("LC_MAX_SESSION_SECONDS", None)
        value = env if env is not None else self._required_int("max-session-seconds")
        return self._check_range("max-session-seconds", value)

    def stall_seconds(self):
        env = self._env_int("LC_STALL_SECONDS", None)
        value = env if env is not None else self._required_int("stall-seconds")
        return self._check_range("stall-seconds", value)

    def probe_cooldown_seconds(self):
        env = self._env_int("LC_PROBE_COOLDOWN_SECONDS", None)
        value = env if env is not None else self._required_int("probe-cooldown-seconds")
        return self._check_range("probe-cooldown-seconds", value)

    def spin_cap(self):
        env = self._env_int("LC_SPIN_CAP", None)
        if env is not None:
            return env
        return self._required_int("spin-cap")

    def poll_seconds(self):
        env = self._env_int("LC_POLL_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("poll-seconds")

    def tui_autostart_pool(self):
        env = self._env_bool("LC_TUI_AUTOSTART_POOL", None)
        if env is not None:
            return env
        return self._required_bool("tui-autostart-pool")

    def schedules_paused(self):
        return self._required_bool("schedules-paused")

    def schedule_blocks(self):
        return {
            k[len(SCHEDULE_KEY_PREFIX):]: dict(v)
            for k, v in self.load_config().items()
            if k.startswith(SCHEDULE_KEY_PREFIX) and isinstance(v, dict)
        }

    def lifecycle_timeout_seconds(self):
        return self._check_range(
            "lifecycle-timeout-seconds", self._required_int("lifecycle-timeout-seconds"))

    def script_timeout_seconds(self):
        return self._check_range(
            "script-timeout-seconds", self._required_int("script-timeout-seconds"))

    def script_max_running(self):
        return self._check_range("script-max-running", self._required_int("script-max-running"))

    def workflow_config_block_name(self, origin, name):
        return "%s%s-%s" % (WORKFLOW_KEY_PREFIX, origin, name)

    def workflow_config(self, origin, name):
        block = self.load_config().get(self.workflow_config_block_name(origin, name))
        return dict(block) if isinstance(block, dict) else {}

    def workflow_data_root(self):
        return os.path.join(self.data_root(), "workflow-data")

    def workflow_data_dir(self, origin, name):
        return os.path.join(self.workflow_data_root(), origin, name)

    def tui_metrics(self):
        env = self._env_bool("LC_TUI_METRICS", None)
        if env is not None:
            return env
        return self._required_bool("tui-metrics")

    def developer_mode(self):
        env = self._env_bool("LC_DEVELOPER_MODE", None)
        if env is not None:
            return env
        return self._required_bool("developer-mode")

    def tui_upgrade_check_seconds(self):
        env = self._env_int("LC_TUI_UPGRADE_CHECK_SECONDS", None)
        value = env if env is not None else self._required_int("tui-upgrade-check-seconds")
        return self._check_range("tui-upgrade-check-seconds", value)

    def pool_upgrade_check_seconds(self):
        env = self._env_int("LC_POOL_UPGRADE_CHECK_SECONDS", None)
        value = env if env is not None else self._required_int("pool-upgrade-check-seconds")
        return self._check_range("pool-upgrade-check-seconds", value)

    def worker_history(self):
        env = self._env_int("LC_WORKER_HISTORY", None)
        if env is not None:
            return env
        return self._required_int("worker-history")

    def shutdown_grace_seconds(self):
        env = self._env_int("LC_SHUTDOWN_GRACE_SECONDS", None)
        value = env if env is not None else self._required_int("shutdown-grace-seconds")
        return self._check_range("shutdown-grace-seconds", value)

    def tick_failure_cap(self):
        env = self._env_int("LC_TICK_FAILURE_CAP", None)
        if env is not None:
            return env
        return self._required_int("tick-failure-cap")

    def review_rounds_cap(self):
        env = self._env_int("LC_REVIEW_ROUNDS_CAP", None)
        if env is not None:
            return env
        return self._required_int("review-rounds-cap")

    def memory_reserve_fraction(self):
        env = self._env_float("LC_MEMORY_RESERVE_FRACTION", None)
        value = env if env is not None else self._required_float("memory-reserve-fraction")
        return self._check_range("memory-reserve-fraction", value)

    def guidance_budget_bytes(self):
        env = self._env_int("LC_GUIDANCE_BUDGET_BYTES", None)
        value = env if env is not None else self._required_int("guidance-budget-bytes")
        return self._check_range("guidance-budget-bytes", value)

    def guidance_unused_after_deliveries(self):
        env = self._env_int("LC_GUIDANCE_UNUSED_AFTER_DELIVERIES", None)
        value = env if env is not None else self._required_int("guidance-unused-after-deliveries")
        return self._check_range("guidance-unused-after-deliveries", value)

    def guidance_dormant_days(self):
        env = self._env_int("LC_GUIDANCE_DORMANT_DAYS", None)
        value = env if env is not None else self._required_int("guidance-dormant-days")
        return self._check_range("guidance-dormant-days", value)

    def audit_shortcode(self):
        env = self._env("LC_AUDIT_SHORTCODE")
        if env:
            return env
        return self._required_str("audit-shortcode")

    def held_comment_shortcode(self):
        env = self._env("LC_HELD_COMMENT_SHORTCODE")
        if env:
            return env
        return self._required_str("held-comment-shortcode")

    def trusted_authors(self):
        return frozenset(a.casefold() for a in self._required_str("trusted-authors").split())

    def seed_trusted_authors(self, login):
        if self.load_config().get("trusted-authors"):
            return False
        p = self.config_path()
        lines = []
        if os.path.exists(p):
            with open(p) as f:
                lines = f.readlines()
        for i, line in enumerate(lines):
            if line.split(":", 1)[0].strip() == "trusted-authors":
                lines[i] = "trusted-authors: %s\n" % login
                break
        else:
            lines.append("trusted-authors: %s\n" % login)
        with open(p, "w") as f:
            f.writelines(lines)
        self.reload()
        return True

    def editor(self):
        raw = self._env("EDITOR")
        if raw:
            return raw
        return self._required_str("editor")

    def backups_dir(self):
        return self._required_path("backups-dir")

    def backup_interval_minutes(self):
        return self._required_int("backup-interval-minutes")

    def guidance_fetch_minutes(self):
        return self._required_int("guidance-fetch-minutes")

    def backup_retention(self):
        return self._required_int("backup-retention")

    def workflow_retention(self):
        return self._check_range("workflow-retention", self._required_int("workflow-retention"))

    def max_title_length(self):
        return self._required_int("max-title-length")

    def price_sonnet_input_per_mtok(self):
        return self._check_range(
            "price-sonnet-input-per-mtok", self._required_float("price-sonnet-input-per-mtok")
        )

    def price_sonnet_output_per_mtok(self):
        return self._check_range(
            "price-sonnet-output-per-mtok", self._required_float("price-sonnet-output-per-mtok")
        )

    def price_sonnet_cache_write_per_mtok(self):
        return self._check_range(
            "price-sonnet-cache-write-per-mtok",
            self._required_float("price-sonnet-cache-write-per-mtok"),
        )

    def price_sonnet_cache_read_per_mtok(self):
        return self._check_range(
            "price-sonnet-cache-read-per-mtok",
            self._required_float("price-sonnet-cache-read-per-mtok"),
        )

    def price_opus_input_per_mtok(self):
        return self._check_range(
            "price-opus-input-per-mtok", self._required_float("price-opus-input-per-mtok")
        )

    def price_opus_output_per_mtok(self):
        return self._check_range(
            "price-opus-output-per-mtok", self._required_float("price-opus-output-per-mtok")
        )

    def price_opus_cache_write_per_mtok(self):
        return self._check_range(
            "price-opus-cache-write-per-mtok",
            self._required_float("price-opus-cache-write-per-mtok"),
        )

    def price_opus_cache_read_per_mtok(self):
        return self._check_range(
            "price-opus-cache-read-per-mtok",
            self._required_float("price-opus-cache-read-per-mtok"),
        )

    def price_haiku_input_per_mtok(self):
        return self._check_range(
            "price-haiku-input-per-mtok", self._required_float("price-haiku-input-per-mtok")
        )

    def price_haiku_output_per_mtok(self):
        return self._check_range(
            "price-haiku-output-per-mtok", self._required_float("price-haiku-output-per-mtok")
        )

    def price_haiku_cache_write_per_mtok(self):
        return self._check_range(
            "price-haiku-cache-write-per-mtok",
            self._required_float("price-haiku-cache-write-per-mtok"),
        )

    def price_haiku_cache_read_per_mtok(self):
        return self._check_range(
            "price-haiku-cache-read-per-mtok",
            self._required_float("price-haiku-cache-read-per-mtok"),
        )

    def usage_pricing(self):
        return {
            "sonnet": ModelRates(
                input=self.price_sonnet_input_per_mtok(),
                output=self.price_sonnet_output_per_mtok(),
                cache_write=self.price_sonnet_cache_write_per_mtok(),
                cache_read=self.price_sonnet_cache_read_per_mtok(),
            ),
            "opus": ModelRates(
                input=self.price_opus_input_per_mtok(),
                output=self.price_opus_output_per_mtok(),
                cache_write=self.price_opus_cache_write_per_mtok(),
                cache_read=self.price_opus_cache_read_per_mtok(),
            ),
            "haiku": ModelRates(
                input=self.price_haiku_input_per_mtok(),
                output=self.price_haiku_output_per_mtok(),
                cache_write=self.price_haiku_cache_write_per_mtok(),
                cache_read=self.price_haiku_cache_read_per_mtok(),
            ),
        }

    def personal_origin(self):
        v = self.load_config().get("personal-origin")
        return v or None

    def context_artifact_types(self):
        raw = self.load_config().get("context-artifact-types")
        return frozenset((raw or "spec").split())

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
        self.reload()

    def spawn_id(self):
        return self._env("LC_SPAWNID")

    def worker_role(self):
        return self._env("LC_ROLE")

    def is_worker(self):
        return bool(self._env("LC_WORKER"))

    def spawn_cmd(self):
        return self._env("LC_SPAWN_CMD")
