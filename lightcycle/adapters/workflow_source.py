import os
import shutil
import subprocess
import tempfile
import tomllib

from lightcycle.domain.workflows.identity import parse_pin
from lightcycle.ports.workflow_source import (
    FetchedBundle,
    OriginRegistration,
    WorkflowSourceError,
    WorkflowSourcePort,
)

_MANIFEST = "source.toml"
_REGISTRY = "origin.toml"


def _toml_str(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


class WorkflowSourceAdapter(WorkflowSourcePort):
    def __init__(self, config, workflow_bundle):
        self._config = config
        self._workflow_bundle = workflow_bundle

    def _root(self):
        return os.path.join(self._config.data_root(), "workflows")

    def _origin_dir(self, origin):
        return os.path.join(self._root(), origin)

    def _bundle_dir(self, origin, sha):
        return os.path.join(self._origin_dir(origin), sha)

    def _read_dir_texts(self, checkout_dir, name):
        d = os.path.join(checkout_dir, name)
        if not os.path.isdir(d):
            return {}
        texts = {}
        for entry in os.scandir(d):
            if entry.name.endswith(".md"):
                with open(entry.path) as f:
                    texts[entry.name[:-3]] = f.read()
        return texts

    def _read_scripts(self, checkout_dir):
        root = os.path.join(checkout_dir, "scripts")
        if not os.path.isdir(root) or os.path.islink(root):
            return {}
        scripts = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            for name in filenames:
                full = os.path.join(dirpath, name)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                with open(full, "rb") as f:
                    data = f.read()
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                scripts[rel] = (data, bool(os.stat(full).st_mode & 0o111))
        return scripts

    def fetch(self, url, ref):
        checkout = tempfile.mkdtemp(prefix="lc-workflow-src-")
        try:
            try:
                subprocess.run(["git", "clone", "--quiet", url, checkout],
                               check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                raise WorkflowSourceError(
                    "could not clone %s: %s" % (url, e.stderr.strip())) from e
            if ref:
                try:
                    subprocess.run(["git", "-C", checkout, "checkout", "--quiet", ref],
                                   check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError:
                    raise WorkflowSourceError("ref %r not found in %s" % (ref, url))
            try:
                sha = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"],
                                     check=True, capture_output=True, text=True).stdout.strip()
            except subprocess.CalledProcessError as e:
                raise WorkflowSourceError(
                    "could not resolve HEAD in checkout of %s: %s"
                    % (url, e.stderr.strip())) from e
            with open(os.path.join(checkout, _MANIFEST)) as f:
                manifest = f.read()
            steps = self._read_dir_texts(checkout, "steps")
            workflows = self._read_dir_texts(checkout, "workflows")
            fragments = self._read_dir_texts(checkout, "fragments")
            scripts = self._read_scripts(checkout)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)
        return FetchedBundle(manifest=manifest, sha=sha, steps=steps, workflows=workflows,
                             fragments=fragments, scripts=scripts)

    def read_manifest(self, checkout_dir):
        with open(os.path.join(checkout_dir, _MANIFEST)) as f:
            return f.read()

    def pin(self, origin, bundle):
        target = self._bundle_dir(origin, bundle.sha)
        if os.path.isdir(target):
            return target
        tmp = target + ".%d.tmp" % os.getpid()
        os.makedirs(tmp, exist_ok=True)
        with open(os.path.join(tmp, _MANIFEST), "w") as f:
            f.write(bundle.manifest)
        for name, texts in (("steps", bundle.steps), ("workflows", bundle.workflows),
                             ("fragments", bundle.fragments)):
            if not texts:
                continue
            os.makedirs(os.path.join(tmp, name), exist_ok=True)
            for role, text in texts.items():
                with open(os.path.join(tmp, name, "%s.md" % role), "w") as f:
                    f.write(text)
        for rel, (data, executable) in bundle.scripts.items():
            dest = os.path.join(tmp, "scripts", *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
            os.chmod(dest, 0o755 if executable else 0o644)
        os.makedirs(self._origin_dir(origin), exist_ok=True)
        os.replace(tmp, target)
        return target

    def has_version(self, origin, sha):
        return os.path.isdir(self._bundle_dir(origin, sha))

    def pinned_bundle(self, origin, sha):
        return self._bundle_dir(origin, sha)

    def current_sha(self, origin):
        registry = self.read_registry(origin)
        return registry.current if registry else None

    def unresolvable_reason(self, url, ref):
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--exit-code", url, ref or "HEAD"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return "%s is not reachable right now" % url
        if result.returncode == 0:
            return None
        if result.returncode == 2:
            return "ref %r no longer resolves against %s" % (ref, url)
        return "%s is not reachable right now" % url

    def workflow_names(self, origin, sha):
        d = os.path.join(self._bundle_dir(origin, sha), "workflows")
        if not os.path.isdir(d):
            return []
        return sorted(e.name[:-3] for e in os.scandir(d) if e.name.endswith(".md"))

    def write_registry(self, origin, url, ref, current, writable):
        os.makedirs(self._origin_dir(origin), exist_ok=True)
        text = "url = %s\nref = %s\ncurrent = %s\nwritable = %s\n" % (
            _toml_str(url), _toml_str(ref or ""), _toml_str(current),
            "true" if writable else "false")
        path = os.path.join(self._origin_dir(origin), _REGISTRY)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        try:
            with open(tmp, "w") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def read_registry(self, origin):
        path = os.path.join(self._origin_dir(origin), _REGISTRY)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return OriginRegistration(
            url=data.get("url"), ref=data.get("ref"), current=data.get("current"),
            writable=data.get("writable") is True)

    def list_origins(self):
        root = self._root()
        if not os.path.isdir(root):
            return []
        return sorted(e.name for e in os.scandir(root) if e.is_dir())

    def list_versions(self, origin):
        d = self._origin_dir(origin)
        if not os.path.isdir(d):
            return []
        entries = [(e.name, e.stat().st_mtime) for e in os.scandir(d)
                   if e.is_dir() and not e.name.endswith(".tmp")]
        entries.sort(key=lambda e: e[1], reverse=True)
        return [name for name, _ in entries]

    def remove_version(self, origin, sha):
        shutil.rmtree(self._bundle_dir(origin, sha), ignore_errors=True)

    def remove_origin(self, origin):
        shutil.rmtree(self._origin_dir(origin), ignore_errors=True)

    def resolve_agent(self, role, pin):
        parsed = parse_pin(pin) if pin else None
        bundle = self.pinned_bundle(parsed[0], parsed[2]) if parsed else None
        roots = ([bundle] if bundle else []) + [self._config.prompts_root()]
        return self._workflow_bundle.parse_step(role, roots)
