import os
import signal
import subprocess

_DRAIN_SECONDS = 5


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_in_group(argv, *, timeout, capture_output=False, check=False, input=None, **popen_kwargs):
    if capture_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE
    if input is not None:
        popen_kwargs["stdin"] = subprocess.PIPE
    proc = subprocess.Popen(argv, start_new_session=True, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        _kill_group(proc)
        try:
            proc.communicate(timeout=_DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        raise expired
    except BaseException:
        _kill_group(proc)
        try:
            proc.communicate(timeout=_DRAIN_SECONDS)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        raise
    code = proc.returncode
    if check and code:
        raise subprocess.CalledProcessError(code, argv, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(argv, code, stdout, stderr)
