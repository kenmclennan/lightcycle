import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lightcycle import frontmatter
from lightcycle.config_ranges import check_range, parse_bool
from lightcycle.config_reload import (
    RELOAD_REJECTED,
    RELOAD_RELOADED,
    RELOAD_UNCHANGED,
    RESTART_REQUIRED_KEYS,
    ConfigReloadResult,
    rejection_reason,
    restart_required,
)
from lightcycle.config_schedules import (
    SCHEDULE_KEY_PREFIX,
    WORKFLOW_KEY_PREFIX,
    is_obsolete_key,
    schedule_blocks,
    workflow_config,
    workflow_config_block_name,
)
from lightcycle.config_seeds import (
    _SEED_KEYS,
    default_config_text,
    missing_seed_keys,
    seed_key_names,
    with_trusted_authors,
)
from lightcycle.domain.pool import ModelRates

__all__ = [
    "RESTART_REQUIRED_KEYS",
    "SCHEDULE_KEY_PREFIX",
    "WORKFLOW_KEY_PREFIX",
]


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
    "ci-check-ceiling-seconds": "LC_CI_CHECK_CEILING_SECONDS",
    "ci-start-window-seconds": "LC_CI_START_WINDOW_SECONDS",
    "ci-no-workflows-wait-seconds": "LC_CI_NO_WORKFLOWS_WAIT_SECONDS",
    "probe-cooldown-seconds": "LC_PROBE_COOLDOWN_SECONDS",
    "spin-cap": "LC_SPIN_CAP",
    "poll-seconds": "LC_POLL_SECONDS",
    "github-poll-seconds": "LC_GITHUB_POLL_SECONDS",
    "github-reserve-calls": "LC_GITHUB_RESERVE_CALLS",
    "github-view-refresh-polls": "LC_GITHUB_VIEW_REFRESH_POLLS",
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
    "guidance-shortcode": "LC_GUIDANCE_SHORTCODE",
    "memory-reserve-fraction": "LC_MEMORY_RESERVE_FRACTION",
    "guidance-budget-bytes": "LC_GUIDANCE_BUDGET_BYTES",
    "guidance-unused-after-deliveries": "LC_GUIDANCE_UNUSED_AFTER_DELIVERIES",
    "guidance-dormant-days": "LC_GUIDANCE_DORMANT_DAYS",
}

_BLANK = (None, "", {})

@dataclass(frozen=True)
class ResolvedSetting:
    key: str
    value: object
    error: Optional[str]
    state: str
    env_var: Optional[str]
    seed: Optional[str]


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

    def prepend_path(self, directory):
        current = self._environ.get("PATH", "")
        parts = current.split(os.pathsep) if current else []
        if parts and parts[0] == directory:
            return
        self._environ["PATH"] = os.pathsep.join([directory] + [p for p in parts if p != directory])

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
            return self._reject(mtime, rejection_reason(bad))
        self._rejected = None
        return ConfigReloadResult(
            RELOAD_RELOADED, mtime=mtime,
            restart_required=self._restart_required(candidate, start_values or {}))

    def _reject(self, mtime, reason):
        self._rejected = (mtime,)
        return ConfigReloadResult(RELOAD_REJECTED, reason=reason, mtime=mtime)

    def _restart_required(self, candidate, start_values):
        return restart_required(
            candidate, start_values, lambda k: self._env(_ENV_OVERRIDE_VARS[k]) is not None)

    def _default_config_text(self):
        return default_config_text()

    def _missing_seed_keys(self, existing):
        return missing_seed_keys(existing)

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
        seed_names = seed_key_names()
        return tuple(
            k for k, v in self.load_config().items() if is_obsolete_key(k, v, seed_names))

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
        try:
            return check_range(key, value)
        except ValueError as e:
            raise ConfigValueError(str(e))

    @staticmethod
    def _parse_bool(key, raw):
        try:
            return parse_bool(key, raw)
        except ValueError as e:
            raise ConfigValueError(str(e))

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

    def ci_check_ceiling_seconds(self):
        env = self._env_int("LC_CI_CHECK_CEILING_SECONDS", None)
        value = env if env is not None else self._required_int("ci-check-ceiling-seconds")
        return self._check_range("ci-check-ceiling-seconds", value)

    def ci_start_window_seconds(self):
        env = self._env_int("LC_CI_START_WINDOW_SECONDS", None)
        value = env if env is not None else self._required_int("ci-start-window-seconds")
        return self._check_range("ci-start-window-seconds", value)

    def ci_no_workflows_wait_seconds(self):
        env = self._env_int("LC_CI_NO_WORKFLOWS_WAIT_SECONDS", None)
        value = env if env is not None else self._required_int("ci-no-workflows-wait-seconds")
        return self._check_range("ci-no-workflows-wait-seconds", value)

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

    def github_poll_seconds(self):
        env = self._env_int("LC_GITHUB_POLL_SECONDS", None)
        if env is not None:
            return env
        return self._required_int("github-poll-seconds")

    def github_reserve_calls(self):
        env = self._env_int("LC_GITHUB_RESERVE_CALLS", None)
        value = env if env is not None else self._required_int("github-reserve-calls")
        return self._check_range("github-reserve-calls", value)

    def github_view_refresh_polls(self):
        env = self._env_int("LC_GITHUB_VIEW_REFRESH_POLLS", None)
        value = env if env is not None else self._required_int("github-view-refresh-polls")
        return self._check_range("github-view-refresh-polls", value)

    def tui_autostart_pool(self):
        env = self._env_bool("LC_TUI_AUTOSTART_POOL", None)
        if env is not None:
            return env
        return self._required_bool("tui-autostart-pool")

    def schedules_paused(self):
        return self._required_bool("schedules-paused")

    def schedule_blocks(self):
        return schedule_blocks(self.load_config())

    def lifecycle_timeout_seconds(self):
        return self._check_range(
            "lifecycle-timeout-seconds", self._required_int("lifecycle-timeout-seconds"))

    def script_timeout_seconds(self):
        return self._check_range(
            "script-timeout-seconds", self._required_int("script-timeout-seconds"))

    def script_max_running(self):
        return self._check_range("script-max-running", self._required_int("script-max-running"))

    def workflow_config_block_name(self, origin, name):
        return workflow_config_block_name(origin, name)

    def workflow_config(self, origin, name):
        return workflow_config(self.load_config(), origin, name)

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

    def guidance_shortcode(self):
        env = self._env("LC_GUIDANCE_SHORTCODE")
        if env:
            return env
        return self._required_str("guidance-shortcode")

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
        with open(p, "w") as f:
            f.writelines(with_trusted_authors(lines, login))
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
        return frozenset(self._required_str("context-artifact-types").split())

    def context_artifact_project(self):
        return self._required_str("context-artifact-project")

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
