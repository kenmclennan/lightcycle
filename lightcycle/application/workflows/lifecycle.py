import os
from dataclasses import dataclass

from lightcycle.domain.work import hook_log_label
from lightcycle.domain.workflows.lifecycle import (
    SCRIPTS_PREFIX,
    WorkflowLifecycle,
    lifecycle_problems,
    missing_required_keys,
    parse_lifecycle,
    workflow_script_env,
)
from lightcycle.frontmatter import split_frontmatter
from lightcycle.ports.workflow_source import WorkflowSourceError


def valid_segment(segment):
    return bool(segment) and segment not in (".", "..") and "/" not in segment \
        and os.sep not in segment and "\0" not in segment


@dataclass(frozen=True)
class HookOutcome:
    ok: bool
    detail: str = ""


def describe_result(origin, name, hook, result, timeout):
    label = "workflow %s/%s %s hook" % (origin, name, hook)
    if result.timed_out:
        text = "%s timed out after %ss" % (label, timeout)
    elif result.exit_code is None:
        text = "%s could not start" % label
    elif result.exit_code != 0:
        text = "%s exited %d" % (label, result.exit_code)
    else:
        return "%s succeeded" % label
    if result.output.strip():
        text += ": " + result.output.strip()
    if result.log_path:
        text += "\nlog: %s" % result.log_path
    return text


def bundle_lifecycles(bundle):
    found = {}
    for name in sorted(bundle.workflows):
        meta, _ = split_frontmatter(bundle.workflows[name] or "")
        try:
            lifecycle = parse_lifecycle(meta)
        except ValueError as e:
            raise WorkflowSourceError("workflow %s: %s" % (name, e))
        if lifecycle is not None:
            found[name] = lifecycle
    return found


def fetched_bundle_problems(bundle):
    problems = {}
    scripts = bundle.scripts

    def exists(path):
        return path[len(SCRIPTS_PREFIX):] in scripts

    def is_executable(path):
        return scripts[path[len(SCRIPTS_PREFIX):]][1]

    for name in sorted(bundle.workflows):
        meta, _ = split_frontmatter(bundle.workflows[name] or "")
        try:
            lifecycle = parse_lifecycle(meta)
        except ValueError as e:
            problems[name] = [str(e)]
            continue
        if lifecycle is None:
            continue
        found = lifecycle_problems(lifecycle, exists, is_executable)
        if found:
            problems[name] = found
    return problems


def directory_lifecycle(bundle_port, directory, name):
    try:
        return parse_lifecycle(bundle_port.workflow_meta(name, directory)), []
    except ValueError as e:
        return None, [str(e)]


def directory_lifecycle_problems(bundle_port, fs, directory, name):
    lifecycle, problems = directory_lifecycle(bundle_port, directory, name)
    if lifecycle is None:
        return problems

    def path_of(rel):
        return os.path.join(directory, *rel.split("/"))

    return lifecycle_problems(
        lifecycle,
        lambda rel: fs.exists(path_of(rel)),
        lambda rel: fs.is_executable(path_of(rel)))


def validate_fetched_bundle(bundle):
    problems = fetched_bundle_problems(bundle)
    if problems:
        detail = "; ".join(
            "%r: %s" % (wf, "; ".join(messages)) for wf, messages in sorted(problems.items()))
        raise WorkflowSourceError("bundle has lifecycle problem(s) - %s" % detail)


class WorkflowLifecycleService:
    def __init__(self, source, bundle, config, runner):
        self._source = source
        self._bundle = bundle
        self._config = config
        self._runner = runner

    def declared(self, origin, name, sha):
        directory = self._source.pinned_bundle(origin, sha)
        meta = self._bundle.workflow_meta(name, directory)
        return parse_lifecycle(meta)

    def data_dir(self, origin, name):
        return self._config.workflow_data_dir(origin, name)

    def data_dir_exists(self, origin, name):
        return self._runner.data_dir_exists(self.data_dir(origin, name))

    def remove_data_dir(self, origin, name):
        self._runner.remove_data_dir(self.data_dir(origin, name))

    def origin_dir_exists(self, origin):
        return self._runner.data_dir_exists(self._origin_dir(origin))

    def remove_empty_origin_dir(self, origin):
        self._runner.remove_empty_dir(self._origin_dir(origin))

    def _origin_dir(self, origin):
        return os.path.dirname(self.data_dir(origin, "x"))

    def kept_data_dirs(self, origin):
        root = os.path.dirname(self.data_dir(origin, "x"))
        return [os.path.join(root, n) for n in self._runner.list_data_dirs(root)]

    def purge(self, origin, name=None):
        for segment in (origin, name):
            if segment is not None and not valid_segment(segment):
                raise WorkflowSourceError(
                    "%r is not a single path segment; name an origin and workflow" % segment)
        if name is not None:
            targets = [self.data_dir(origin, name)]
            targets = [t for t in targets if self._runner.data_dir_exists(t)]
        else:
            targets = self.kept_data_dirs(origin)
        for target in targets:
            self._runner.remove_data_dir(target)
        if name is None:
            self._runner.remove_data_dir(os.path.dirname(self.data_dir(origin, "x")))
        return targets

    def hook_invocation(self, hook, origin, name, sha, lifecycle=None, bundle_dir=None,
                        data_dir=None, config=None, from_sha=None, to_sha=None):
        bundle_dir = bundle_dir or self._source.pinned_bundle(origin, sha)
        lifecycle = lifecycle or self.declared(origin, name, sha)
        data_dir = data_dir or self.data_dir(origin, name)
        config = self._config.workflow_config(origin, name) if config is None else config
        script = os.path.join(bundle_dir, *lifecycle.script(hook).split("/"))
        env = workflow_script_env(
            self._config.agent_env(), hook, origin, name, data_dir, bundle_dir, sha,
            lifecycle, config, from_sha=from_sha, to_sha=to_sha)
        return script, data_dir, env

    def ensure_data_dir(self, origin, name):
        path = self.data_dir(origin, name)
        self._runner.ensure_data_dir(path)
        return path

    def script_environment(self, origin, name, sha, bundle_dir, kind, extra):
        declared = self.declared(origin, name, sha) or WorkflowLifecycle()
        config = self._config.workflow_config(origin, name)
        env = workflow_script_env(
            self._config.agent_env(), None, origin, name, self.data_dir(origin, name),
            bundle_dir, sha, declared, config)
        env["LC_WORKFLOW_SCRIPT"] = kind
        env.update(extra)
        return env, missing_required_keys(declared, config)

    def run(self, hook, origin, name, sha, **kwargs):
        script, data_dir, env = self.hook_invocation(hook, origin, name, sha, **kwargs)
        self._runner.ensure_data_dir(data_dir)
        timeout = self._config.lifecycle_timeout_seconds()
        result = self._runner.run(
            script, data_dir, env, timeout, hook_log_label(origin, name, hook))
        return HookOutcome(ok=result.ok, detail=describe_result(origin, name, hook, result, timeout))

    def install(self, origin, name, sha, **kwargs):
        return self.run("install", origin, name, sha, **kwargs)

    def upgrade(self, origin, name, from_sha, to_sha, **kwargs):
        return self.run(
            "upgrade", origin, name, to_sha, from_sha=from_sha, to_sha=to_sha, **kwargs)

    def maintain(self, origin, name, sha, **kwargs):
        return self.run("maintain", origin, name, sha, **kwargs)
