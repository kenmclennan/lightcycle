import os
import re
import sys
from dataclasses import dataclass

_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


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


class ProcessListUnreadableError(Exception):
    pass


class RemoteVersionUnavailableError(Exception):
    pass


def parse_process_list(text):
    processes = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        processes.append((int(parts[0]), parts[1] if len(parts) > 1 else ""))
    return processes


def filter_holders(processes, signatures, exclude_pid):
    return [
        (pid, command)
        for pid, command in processes
        if pid != exclude_pid and any(sig in command for sig in signatures)
    ]


def format_holders_message(holders):
    lines = ["lc upgrade refused: the venv is in use by other processes:"]
    lines += ["  %d  %s" % (pid, command) for pid, command in holders]
    lines.append("stop the pool and close any `lc logs -f`, then retry `lc upgrade`.")
    return "\n".join(lines)


def own_entry_points():
    bindir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return [os.path.join(bindir, "lc"), os.path.join(bindir, "lightcycle")]


def venv_signatures():
    return own_entry_points() + ["-m lightcycle"]


def scan_venv_holders(list_processes, exclude_pid=None):
    return filter_holders(
        parse_process_list(list_processes()), venv_signatures(), exclude_pid or os.getpid()
    )


def parse_remote_version(text):
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def _semver(version):
    return tuple(int(part) for part in version.split("."))


def upgrade(current_version, check_only=False, fetch=None,
            install=None, installed=None, holders=None):
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
