import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass

_REMOTE_INIT_URL = "https://raw.githubusercontent.com/kenmclennan/lightcycle/main/lightcycle/__init__.py"
_INSTALL_CMD = ["pipx", "install", "--force", "git+https://github.com/kenmclennan/lightcycle"]
_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
_SEMVER_RE = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass(frozen=True)
class UpgradeResponse:
    current: str
    remote: str
    available: bool
    applied: bool


class VenvBusyError(Exception):
    def __init__(self, holders):
        self.holders = holders
        super().__init__(format_holders_message(holders))


def parse_process_list(text):
    processes = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        processes.append((int(parts[0]), parts[1] if len(parts) > 1 else ""))
    return processes


def filter_holders(processes, root, exclude_pid):
    return [(pid, command) for pid, command in processes if pid != exclude_pid and root in command]


def format_holders_message(holders):
    lines = ["lc upgrade refused: the venv is in use by other processes:"]
    lines += ["  %d  %s" % (pid, command) for pid, command in holders]
    lines.append("stop the pool and close any `lc logs -f`, then retry `lc upgrade`.")
    return "\n".join(lines)


def venv_root():
    return os.path.realpath(sys.prefix)


def list_processes():
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.decode()


def scan_venv_holders(exclude_pid=None):
    return filter_holders(
        parse_process_list(list_processes()), venv_root(), exclude_pid or os.getpid()
    )


def parse_remote_version(text):
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def fetch_remote_version():
    with urllib.request.urlopen(_REMOTE_INIT_URL, timeout=10) as resp:
        version = parse_remote_version(resp.read().decode())
    if version is None:
        raise ValueError("no __version__ found in the remote file")
    return version


def install_upgrade():
    env = dict(os.environ, UV_VENV_CLEAR="1")
    subprocess.run(_INSTALL_CMD, check=True, env=env)


def installed_version():
    try:
        result = subprocess.run(["lc", "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _SEMVER_RE.search(result.stdout)
    return match.group(1) if match else None


def _semver(version):
    return tuple(int(part) for part in version.split("."))


def upgrade(current_version, check_only=False, fetch=fetch_remote_version,
            install=install_upgrade, installed=installed_version, holders=scan_venv_holders):
    remote_version = fetch()
    available = _semver(remote_version) > _semver(current_version)
    applied = False
    if available and not check_only:
        blockers = holders()
        if blockers:
            raise VenvBusyError(blockers)
        install()
        applied = True
        actual = installed()
        if actual:
            remote_version = actual
    return UpgradeResponse(
        current=current_version, remote=remote_version, available=available, applied=applied
    )
