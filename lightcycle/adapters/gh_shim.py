import os
import shlex

from lightcycle.ports.gh_shim import GhShimPort

_TEMPLATE = """#!/bin/sh
shim_dir=%(shim_dir)s
logs=%(logs)s
PATH=$(printf %%s "$PATH" | tr ':' '\\n' | grep -vxF "$shim_dir" | paste -sd: -)
export PATH
gh "$@"
rc=$?
if [ -n "$LC_SPAWNID" ]; then
  file="$logs/gh-calls-$LC_SPAWNID.log"
  src="$LC_SPAWNID"
else
  file="$logs/gh-calls-pool-$(date -u +%%Y%%m%%d).log"
  src=pool
fi
head=
n=0
for a in "$@"; do
  n=$((n + 1))
  [ "$n" -gt 4 ] && break
  head="$head${head:+ }$a"
done
head=$(printf '%%s' "$head" | tr '\\n\\t' '  ' | cut -c1-120)
{ printf '%%s\\t%%s\\t%%s\\t%%s\\n' "$(date +%%s)" "$src" "$rc" "$head" >> "$file"; } 2>/dev/null
exit "$rc"
"""


def shim_script(root):
    return _TEMPLATE % {
        "shim_dir": shlex.quote(os.path.join(root, "shims")),
        "logs": shlex.quote(os.path.join(root, "logs")),
    }


def ensure_gh_shim(root):
    directory = os.path.join(root, "shims")
    os.makedirs(directory, exist_ok=True)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    path = os.path.join(directory, "gh")
    script = shim_script(root)
    try:
        with open(path) as f:
            current = f.read()
        executable = os.access(path, os.X_OK)
    except OSError:
        current = None
        executable = False
    if current != script or not executable:
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w") as f:
            f.write(script)
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)
    return directory


class GhShimAdapter(GhShimPort):
    def __init__(self, config):
        self._config = config

    def install(self):
        directory = ensure_gh_shim(self._config.data_root())
        self._config.prepend_path(directory)
        return directory
