import re
from dataclasses import dataclass, field
from typing import Dict, Tuple

from lightcycle.domain.schedule.cron import parse_cron

HOOKS = ("install", "upgrade", "maintain")
SCRIPTS_PREFIX = "scripts/"
KEY_SHAPE = re.compile(r"^[a-z0-9-]+$")
_LIFECYCLE_FIELDS = HOOKS + ("cron",)
_REQUIRED = "required"
_OPTIONAL = "optional"


@dataclass(frozen=True)
class WorkflowLifecycle:
    install: str = ""
    upgrade: str = ""
    maintain: str = ""
    cron: str = ""
    config: Tuple[Tuple[str, bool], ...] = ()
    examples: Dict[str, str] = field(default_factory=dict)

    def script(self, hook):
        return getattr(self, hook)

    def declared_hooks(self):
        return tuple(h for h in HOOKS if self.script(h))

    def required_keys(self):
        return tuple(k for k, required in self.config if required)

    def config_keys(self):
        return tuple(k for k, _ in self.config)


def parse_lifecycle(meta):
    block = meta.get("lifecycle")
    if block is None and "config" not in meta and "config-example" not in meta:
        return None
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ValueError("lifecycle: must be a block of install/upgrade/maintain/cron lines")
    unknown = sorted(set(block) - set(_LIFECYCLE_FIELDS))
    if unknown:
        raise ValueError("lifecycle: has unknown key(s) %s" % ", ".join(unknown))
    declared = meta.get("config", {})
    if not isinstance(declared, dict):
        raise ValueError("config: must be a block of <key>: required|optional lines")
    config = []
    for key, value in declared.items():
        if value not in (_REQUIRED, _OPTIONAL):
            raise ValueError(
                "config: key %r must be %s or %s (got %r)" % (key, _REQUIRED, _OPTIONAL, value))
        config.append((key, value == _REQUIRED))
    examples = meta.get("config-example", {})
    if not isinstance(examples, dict):
        raise ValueError("config-example: must be a block of <key>: <value> lines")
    return WorkflowLifecycle(
        install=block.get("install", ""),
        upgrade=block.get("upgrade", ""),
        maintain=block.get("maintain", ""),
        cron=block.get("cron", ""),
        config=tuple(config),
        examples=dict(examples),
    )


def env_name(key):
    return key.upper().replace("-", "_")


def script_path_shape_problem(label, path):
    if not path.startswith(SCRIPTS_PREFIX) or len(path) == len(SCRIPTS_PREFIX):
        return "%s %r must be a path under %s" % (label, path, SCRIPTS_PREFIX)
    if ".." in path.split("/"):
        return "%s %r must not contain a '..' segment" % (label, path)
    return None


def _path_problem(hook, path):
    return script_path_shape_problem("lifecycle %s" % hook, path)


def lifecycle_problems(lifecycle, exists, is_executable):
    problems = []
    for hook in lifecycle.declared_hooks():
        path = lifecycle.script(hook)
        shape = _path_problem(hook, path)
        if shape:
            problems.append(shape)
        elif not exists(path):
            problems.append("lifecycle %s script %s does not exist" % (hook, path))
        elif not is_executable(path):
            problems.append("lifecycle %s script %s is not executable" % (hook, path))
    if lifecycle.maintain and not lifecycle.cron:
        problems.append("lifecycle maintain needs a cron")
    if lifecycle.cron and not lifecycle.maintain:
        problems.append("lifecycle cron is set but there is no maintain script")
    if lifecycle.cron:
        try:
            parse_cron(lifecycle.cron)
        except ValueError as e:
            problems.append("lifecycle cron %r is invalid: %s" % (lifecycle.cron, e))
    seen = {}
    for key, required in lifecycle.config:
        if not KEY_SHAPE.match(key):
            problems.append("config key %r must match [a-z0-9-]+" % key)
        name = env_name(key)
        if name in seen:
            problems.append(
                "config keys %r and %r both map to LC_WORKFLOW_CONFIG_%s"
                % (seen[name], key, name))
        seen[name] = key
        if required and key not in lifecycle.examples:
            problems.append("required config key %r has no config-example value" % key)
    return problems


def workflow_script_env(base_env, hook, origin, name, data_dir, bundle_dir, sha,
                        lifecycle, config, from_sha=None, to_sha=None):
    env = dict(base_env)
    if hook is not None:
        env["LC_WORKFLOW_HOOK"] = hook
    env["LC_WORKFLOW_ORIGIN"] = origin
    env["LC_WORKFLOW_NAME"] = name
    env["LC_WORKFLOW_DATA_DIR"] = data_dir
    env["LC_WORKFLOW_BUNDLE_DIR"] = bundle_dir
    env["LC_WORKFLOW_SHA"] = sha
    if from_sha is not None:
        env["LC_WORKFLOW_FROM_SHA"] = from_sha
    if to_sha is not None:
        env["LC_WORKFLOW_TO_SHA"] = to_sha
    for key in lifecycle.config_keys():
        value = config.get(key)
        if value is None or not str(value).strip():
            continue
        env["LC_WORKFLOW_CONFIG_%s" % env_name(key)] = str(value)
    return env


def missing_required_keys(lifecycle, config):
    return tuple(
        k for k in lifecycle.required_keys()
        if config.get(k) is None or not str(config.get(k)).strip())
