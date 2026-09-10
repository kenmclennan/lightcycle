import os

from lightcycle.ports.worker_log import WorkerLogPort


def read_from(path, offset):
    if not path or not os.path.exists(path):
        return b"", offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    return data, offset + len(data)


def read_from_bounded(path, offset, max_bytes):
    if not path or not os.path.exists(path):
        return b"", offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(max_bytes)
    return data, offset + len(data)


def read_tail(path, max_bytes):
    if not path or not os.path.exists(path):
        return b"", 0
    start = max(0, os.path.getsize(path) - max_bytes)
    if start == 0:
        return read_from(path, start)
    data, offset = read_from(path, start - 1)
    preceding, rest = data[:1], data[1:]
    if preceding != b"\n":
        newline = rest.find(b"\n")
        rest = rest[newline + 1:] if newline != -1 else b""
    return rest, offset


def iter_lines(path):
    if not path or not os.path.exists(path):
        return
    with open(path, "rb") as f:
        for raw in f:
            yield raw.decode("utf-8", errors="replace")


def run_log_path(root):
    return os.path.join(root, "logs", "run.log")


def append_run_log(root, text):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(run_log_path(root), "a") as f:
        f.write(text)


def list_worker_log_files(root):
    logs_dir = os.path.join(root, "logs")
    if not os.path.isdir(logs_dir):
        return []
    return sorted(
        os.path.join(logs_dir, e.name)
        for e in os.scandir(logs_dir)
        if e.is_file() and e.name.startswith("worker-") and e.name.endswith(".log")
    )


class WorkerLogAdapter(WorkerLogPort):
    def __init__(self, config):
        self._config = config

    def read_from(self, path, offset):
        return read_from(path, offset)

    def read_from_bounded(self, path, offset, max_bytes):
        return read_from_bounded(path, offset, max_bytes)

    def read_tail(self, path, max_bytes):
        return read_tail(path, max_bytes)

    def iter_lines(self, path):
        return iter_lines(path)

    def list_worker_log_files(self, root):
        return list_worker_log_files(root)

    def append_run_log(self, text):
        return append_run_log(self._config.data_root(), text)
