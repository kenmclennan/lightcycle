import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile

from lightcycle.adapters.process_group import run_in_group

PS_TIMEOUT_SECONDS = 10
UNREGISTERED_SCRATCH_MIN_AGE_SECONDS = 600
MARKER_NAME = ".lc-reap-term-at"

_TMPDIR_TOKEN = re.compile(r"(?:^|\s)TMPDIR=(\S*)")


def scratch_root(root):
    key = hashlib.sha256(os.path.realpath(root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "lc-scratch-" + key)


def scratch_dir(root, spawnid):
    return os.path.join(scratch_root(root), spawnid)


def create_scratch(root, spawnid):
    path = scratch_dir(root, spawnid)
    os.makedirs(scratch_root(root), exist_ok=True)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _scan_proc():
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/environ" % name, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        values = [
            item[len(b"TMPDIR="):].decode("utf-8", "replace")
            for item in raw.split(b"\0")
            if item.startswith(b"TMPDIR=")
        ]
        found.append((int(name), values))
    return found


def _scan_ps():
    out = run_in_group(
        ["ps", "-ww", "-E", "-A", "-o", "pid=,command="],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=PS_TIMEOUT_SECONDS,
    )
    if out.returncode != 0:
        return None
    found = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        found.append((int(parts[0]), _TMPDIR_TOKEN.findall(parts[1])))
    return found


def scan_environments():
    try:
        if sys.platform.startswith("linux") and os.path.isdir("/proc"):
            return _scan_proc()
        if sys.platform == "darwin":
            return _scan_ps()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def _under(value, path):
    return value == path or value.startswith(path.rstrip("/") + "/")


def _own_group(pid, own_pgid):
    try:
        return os.getpgid(pid) == own_pgid
    except OSError:
        return False


def tagged_pids(paths, scan=scan_environments, own_pid=None, own_pgid=None):
    if own_pid is None:
        own_pid = os.getpid()
    if own_pgid is None:
        own_pgid = os.getpgid(0)
    scanned = scan()
    if scanned is None:
        return None
    result = {p: [] for p in paths}
    for pid, values in scanned:
        if pid <= 1 or pid == own_pid or not values:
            continue
        hits = [p for p in paths if any(_under(v, p) for v in values)]
        if not hits or _own_group(pid, own_pgid):
            continue
        for p in hits:
            result[p].append(pid)
    return result


def signal_tagged(pids, sig):
    for pid in pids:
        for s in (signal.SIGCONT, sig):
            try:
                os.kill(pid, s)
            except OSError:
                pass


def reap_scratch(term_at, tagged, group_alive, grace_seconds, now):
    if tagged is None:
        return "keep"
    if not group_alive and not tagged:
        return "delete"
    if term_at is None:
        return "term"
    if now - term_at >= grace_seconds:
        return "kill"
    return "wait"


def read_marker(path):
    try:
        with open(os.path.join(path, MARKER_NAME)) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def write_marker(path, stamp):
    try:
        with open(os.path.join(path, MARKER_NAME), "w") as f:
            f.write(repr(float(stamp)))
    except OSError:
        pass


def stray_scratch_dirs(root, registered_spawnids, now):
    base = scratch_root(root)
    try:
        names = os.listdir(base)
    except OSError:
        return []
    found = []
    for name in sorted(names):
        if name in registered_spawnids:
            continue
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        if read_marker(path) is not None:
            found.append(path)
            continue
        try:
            age = now - os.stat(path).st_mtime
        except OSError:
            continue
        if age >= UNREGISTERED_SCRATCH_MIN_AGE_SECONDS:
            found.append(path)
    return found
