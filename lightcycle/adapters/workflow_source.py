import os
import shutil
import subprocess
import tempfile
import tomllib

from lightcycle.ports.workflow_source import WorkflowSourcePort

_MANIFEST = "source.toml"
_REGISTRY = "origin.toml"
_BUNDLE_DIRS = ("workflows", "steps")


def _toml_str(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def default_bundle_root(config):
    origin = config.default_origin()
    adapter = WorkflowSourceAdapter(config)
    sha = adapter.current_sha(origin)
    return adapter.bundle_path(origin, sha) if sha else None


class WorkflowSourceAdapter(WorkflowSourcePort):
    def __init__(self, config):
        self._config = config

    def _root(self):
        return os.path.join(self._config.data_root(), "workflows")

    def _origin_dir(self, origin):
        return os.path.join(self._root(), origin)

    def _bundle_dir(self, origin, sha):
        return os.path.join(self._origin_dir(origin), sha)

    def fetch(self, url, ref):
        checkout = tempfile.mkdtemp(prefix="lc-workflow-src-")
        subprocess.run(["git", "clone", "--quiet", url, checkout],
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", checkout, "checkout", "--quiet", ref],
                       check=True, capture_output=True, text=True)
        sha = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"],
                             check=True, capture_output=True, text=True).stdout.strip()
        return checkout, sha

    def read_manifest(self, checkout_dir):
        with open(os.path.join(checkout_dir, _MANIFEST)) as f:
            return f.read()

    def materialize(self, origin, sha, checkout_dir):
        bundle = self._bundle_dir(origin, sha)
        if os.path.isdir(bundle):
            return bundle
        tmp = bundle + ".%d.tmp" % os.getpid()
        os.makedirs(tmp, exist_ok=True)
        shutil.copy2(os.path.join(checkout_dir, _MANIFEST), os.path.join(tmp, _MANIFEST))
        for name in _BUNDLE_DIRS:
            src = os.path.join(checkout_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tmp, name))
        os.makedirs(self._origin_dir(origin), exist_ok=True)
        os.replace(tmp, bundle)
        return bundle

    def has_version(self, origin, sha):
        return os.path.isdir(self._bundle_dir(origin, sha))

    def bundle_path(self, origin, sha):
        return self._bundle_dir(origin, sha)

    def current_sha(self, origin):
        registry = self.read_registry(origin)
        return registry["current"] if registry else None

    def workflow_names(self, origin, sha):
        d = os.path.join(self._bundle_dir(origin, sha), "workflows")
        if not os.path.isdir(d):
            return []
        return sorted(e.name[:-3] for e in os.scandir(d) if e.name.endswith(".md"))

    def write_registry(self, origin, url, ref, current):
        os.makedirs(self._origin_dir(origin), exist_ok=True)
        text = "url = %s\nref = %s\ncurrent = %s\n" % (
            _toml_str(url), _toml_str(ref), _toml_str(current))
        with open(os.path.join(self._origin_dir(origin), _REGISTRY), "w") as f:
            f.write(text)

    def read_registry(self, origin):
        path = os.path.join(self._origin_dir(origin), _REGISTRY)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return {"url": data.get("url"), "ref": data.get("ref"), "current": data.get("current")}

    def list_origins(self):
        root = self._root()
        if not os.path.isdir(root):
            return []
        return sorted(e.name for e in os.scandir(root) if e.is_dir())

    def list_versions(self, origin):
        d = self._origin_dir(origin)
        if not os.path.isdir(d):
            return []
        entries = [(e.name, e.stat().st_mtime) for e in os.scandir(d) if e.is_dir()]
        entries.sort(key=lambda e: e[1], reverse=True)
        return [name for name, _ in entries]

    def remove_version(self, origin, sha):
        shutil.rmtree(self._bundle_dir(origin, sha), ignore_errors=True)

    def remove_origin(self, origin):
        shutil.rmtree(self._origin_dir(origin), ignore_errors=True)

    def cleanup(self, checkout_dir):
        shutil.rmtree(checkout_dir, ignore_errors=True)
