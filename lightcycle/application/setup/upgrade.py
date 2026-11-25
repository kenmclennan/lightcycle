import os
import sys
import time
from dataclasses import dataclass
from typing import Tuple

from lightcycle.domain.workflows.engine_requirement import parse_version


@dataclass(frozen=True)
class UpgradeResponse:
    current: str
    remote: str
    available: bool
    applied: bool
    conflicts: Tuple[str, ...] = ()


class VenvBusyError(Exception):
    def __init__(self, holders):
        self.holders = holders
        super().__init__(format_holders_message(holders))


class BundleRangeError(Exception):
    def __init__(self, conflicts):
        self.conflicts = tuple(conflicts)
        super().__init__("; ".join(self.conflicts))


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


LONG_LIVED_MODULES = ("lightcycle.worker_main", "lightcycle.adapters.worker_session")
LONG_LIVED_VERBS = ("start", "tui")
WAIT_POLL_SECONDS = 1.0


def is_long_lived(command):
    tokens = command.split()
    if any(module in token for token in tokens for module in LONG_LIVED_MODULES):
        return True
    for index, token in enumerate(tokens):
        if os.path.basename(token) in ("lc", "lightcycle"):
            rest = tokens[index + 1:]
            if not rest:
                return False
            if rest[0] in LONG_LIVED_VERBS:
                return True
            return rest[0] == "logs" and any(a in ("-f", "--follow") for a in rest[1:])
    return False


def format_waiting_message(holders):
    lines = ["lc upgrade is waiting for one-shot lc commands to exit (Ctrl-C aborts):"]
    lines += ["  %d  %s" % (pid, command) for pid, command in holders]
    return "\n".join(lines)


def wait_for_one_shot_holders(holders, on_waiting, sleep):
    announced = None
    while True:
        blockers = holders()
        long_lived = [h for h in blockers if is_long_lived(h[1])]
        if long_lived:
            raise VenvBusyError(long_lived)
        if not blockers:
            return
        pids = sorted(pid for pid, _ in blockers)
        if pids != announced and on_waiting:
            on_waiting(blockers)
            announced = pids
        sleep(WAIT_POLL_SECONDS)


def own_entry_points():
    bindir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return [os.path.join(bindir, "lc"), os.path.join(bindir, "lightcycle")]


def venv_signatures():
    return own_entry_points() + ["-m lightcycle"]


def scan_venv_holders(list_processes, exclude_pid=None):
    return filter_holders(
        parse_process_list(list_processes()), venv_signatures(), exclude_pid or os.getpid()
    )


def upgrade(current_version, check_only=False, fetch=None,
            install=None, installed=None, holders=None, bundle_conflicts=None, force=False,
            on_waiting=None, sleep=time.sleep):
    remote_version = fetch()
    available = parse_version(remote_version) > parse_version(current_version)
    applied = False
    conflicts = tuple(bundle_conflicts(remote_version)) if available and bundle_conflicts else ()
    if available and not check_only:
        if conflicts and not force:
            raise BundleRangeError(conflicts)
        wait_for_one_shot_holders(holders, on_waiting, sleep)
        install()
        applied = True
        actual = installed()
        if actual:
            remote_version = actual
    return UpgradeResponse(
        current=current_version, remote=remote_version, available=available, applied=applied,
        conflicts=conflicts,
    )
