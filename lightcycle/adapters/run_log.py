import contextlib
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

TAIL_CHARS = 2000
_KINDS = ("script-", "guard-", "hook-")


@dataclass(frozen=True)
class LoggedRun:
    exit_code: Optional[int]
    stdout: str
    stderr_tail: str
    timed_out: bool
    log_path: Optional[str]


def decode(raw):
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def new_log_path(config, label):
    logs = os.path.join(config.data_root(), "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "%s-%d.log" % (label, int(time.time() * 1000)))


def prune_run_logs(config, label):
    kind = next((k for k in _KINDS if label.startswith(k)), None)
    if kind is None:
        return
    logs = os.path.join(config.data_root(), "logs")
    found = []
    for entry in os.scandir(logs):
        if entry.is_file() and entry.name.startswith(kind) and entry.name.endswith(".log"):
            found.append((entry.stat().st_mtime, entry.name, entry.path))
    found.sort()
    for _, _, path in found[:max(0, len(found) - max(config.worker_history(), 1))]:
        try:
            os.remove(path)
        except OSError:
            pass


def _write(handle, text):
    handle.write(text.encode("utf-8", errors="replace"))
    handle.flush()


def run_logged(config, label, log_path, script_path, cwd, env, stdin_bytes, timeout):
    started = time.time()
    with contextlib.ExitStack() as stack:
        try:
            handle = stack.enter_context(open(log_path, "ab"))
        except OSError:
            handle = None
        if handle is not None:
            _write(handle, "script: %s\nstarted: %s\n--- stderr ---\n" % (
                script_path, time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started))))
            stderr_from = handle.tell()
        kwargs = dict(
            cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=handle if handle is not None else subprocess.PIPE)
        if stdin_bytes is None:
            kwargs["stdin"] = subprocess.DEVNULL
        else:
            kwargs["input"] = stdin_bytes
        exit_code, stdout, timed_out, footer, piped_err = None, "", False, None, ""
        try:
            completed = subprocess.run([script_path], timeout=timeout, **kwargs)
            exit_code = completed.returncode
            stdout = decode(completed.stdout)
            piped_err = decode(completed.stderr)
            footer = "exit %d" % exit_code
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stdout = decode(e.stdout)
            piped_err = decode(e.stderr)
            footer = "timed out after %ss" % timeout
        except OSError as e:
            piped_err = str(e)
            footer = "could not start: %s" % e
        stderr_text = piped_err
        if handle is not None:
            with open(log_path, "rb") as reader:
                reader.seek(stderr_from)
                stderr_text = decode(reader.read())
            stderr_text = stderr_text or piped_err
            _write(handle, "--- stdout ---\n%s%s--- end ---\n%s (%.1fs)\n" % (
                stdout, "" if stdout.endswith("\n") or not stdout else "\n",
                footer, time.time() - started))
    if handle is not None:
        prune_run_logs(config, label)
    return LoggedRun(
        exit_code=exit_code, stdout=stdout, stderr_tail=stderr_text[-TAIL_CHARS:],
        timed_out=timed_out, log_path=log_path if handle is not None else None)
