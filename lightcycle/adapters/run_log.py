import contextlib
import os
import signal
import subprocess
import threading
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


STREAM_JOIN_SECONDS = 5
CHUNK_BYTES = 65536


class _LogTee:
    def __init__(self, handle):
        self._handle = handle
        self._lock = threading.Lock()
        self._section = "stderr"
        self.buffers = {"stdout": [], "stderr": []}

    def feed(self, stream, chunk):
        with self._lock:
            self.buffers[stream].append(chunk)
            if self._handle is None:
                return
            if stream != self._section:
                self._section = stream
                _write(self._handle, "--- %s ---\n" % stream)
            self._handle.write(chunk)
            self._handle.flush()

    def text(self, stream):
        with self._lock:
            return decode(b"".join(self.buffers[stream]))


def _pump(pipe, stream, tee):
    try:
        while True:
            chunk = os.read(pipe.fileno(), CHUNK_BYTES)
            if not chunk:
                return
            tee.feed(stream, chunk)
    except (OSError, ValueError):
        return


def _feed_stdin(proc, stdin_bytes):
    try:
        proc.stdin.write(stdin_bytes)
        proc.stdin.close()
    except (OSError, ValueError):
        return


def _run_streamed(label, script_path, cwd, env, stdin_bytes, timeout, tee, groups, on_spawn):
    proc = subprocess.Popen(
        [script_path], cwd=cwd, env=env,
        stdin=subprocess.DEVNULL if stdin_bytes is None else subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    groups.register(label, proc)
    if on_spawn is not None:
        on_spawn(proc)
    threads = [
        threading.Thread(target=_pump, args=(proc.stdout, "stdout", tee), daemon=True),
        threading.Thread(target=_pump, args=(proc.stderr, "stderr", tee), daemon=True),
    ]
    if stdin_bytes is not None:
        threads.append(threading.Thread(target=_feed_stdin, args=(proc, stdin_bytes), daemon=True))
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    finally:
        groups.release(proc)
    for thread in threads:
        thread.join(STREAM_JOIN_SECONDS)
    proc.stdout.close()
    proc.stderr.close()
    return proc.returncode, timed_out


def run_logged(config, label, log_path, script_path, cwd, env, stdin_bytes, timeout, groups,
               on_spawn=None):
    started_at = time.time()
    started = time.monotonic()
    with contextlib.ExitStack() as stack:
        try:
            handle = stack.enter_context(open(log_path, "ab"))
        except OSError:
            handle = None
        if handle is not None:
            _write(handle, "script: %s\nstarted: %s\n--- stderr ---\n" % (
                script_path, time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at))))
        tee = _LogTee(handle)
        exit_code, timed_out = None, False
        try:
            exit_code, timed_out = _run_streamed(
                label, script_path, cwd, env, stdin_bytes, timeout, tee, groups, on_spawn)
            footer = "timed out after %ss" % timeout if timed_out else "exit %d" % exit_code
            if timed_out:
                exit_code = None
        except OSError as e:
            tee.feed("stderr", str(e).encode("utf-8", errors="replace"))
            footer = "could not start: %s" % e
        stdout, stderr_text = tee.text("stdout"), tee.text("stderr")
        if handle is not None:
            _write(handle, "--- end ---\n%s (%.1fs)\n" % (footer, time.monotonic() - started))
    if handle is not None:
        prune_run_logs(config, label)
    return LoggedRun(
        exit_code=exit_code, stdout=stdout, stderr_tail=stderr_text[-TAIL_CHARS:],
        timed_out=timed_out, log_path=log_path if handle is not None else None)
