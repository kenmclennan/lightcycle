import os
import re
import shutil
import subprocess
import sys
import tempfile

_TOOL_OWNED = re.compile(r"^uv-[0-9a-f]+\.lock$")


def _tool_owned(directory, name):
    if _TOOL_OWNED.match(name):
        return True
    path = os.path.join(directory, name)
    return name.startswith("pytest-of-") and os.path.isdir(path) and not os.listdir(path)


def leftovers(directory):
    return sorted(n for n in os.listdir(directory) if not _tool_owned(directory, n))


def main(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    if not argv:
        print("usage: assert_clean_tmpdir.py -- <command> [args...]", file=sys.stderr)
        return 2
    scratch = tempfile.mkdtemp(prefix="lc-assert-clean-")
    try:
        env = dict(os.environ)
        env["TMPDIR"] = scratch
        code = subprocess.run(argv, env=env, timeout=None).returncode
        remaining = leftovers(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for name in remaining:
        print(f"leftover in TMPDIR: {name}", file=sys.stderr)
    if code != 0:
        return code
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
