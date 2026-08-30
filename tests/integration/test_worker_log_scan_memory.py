import json
import os
import resource
import sys
import tempfile
import unittest

from lightcycle.adapters.fsio import iter_lines
from lightcycle.domain.pool.rate_limit import parse_rate_limit_event
from lightcycle.domain.pool.worker_session import saw_terminal_command

_TARGET_BYTES = 20 * 1024 * 1024
_MULTIBYTE_TEXT = "café ☃ 你好 ❤️ résumé naïve"
_ITERATIONS = 8
_GROWTH_THRESHOLD_BYTES = 5 * 1024 * 1024


def _build_log(path):
    parts = []
    written = 0
    i = 0
    while written < _TARGET_BYTES:
        if i % 200 == 0:
            text = "line %d with multibyte %s content padded %s" % (
                i, _MULTIBYTE_TEXT, "x" * 40,
            )
        else:
            text = "line %d plain ascii content padded %s" % (i, "x" * 60)
        line = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
        ) + "\n"
        encoded = line.encode("utf-8")
        parts.append(encoded)
        written += len(encoded)
        i += 1
    with open(path, "wb") as f:
        f.write(b"".join(parts))


def _ru_maxrss_bytes():
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss
    return rss * 1024


class TestWorkerLogScanMemory(unittest.TestCase):
    def test_repeated_scans_of_a_large_log_leave_rss_flat(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        _build_log(path)
        size = os.path.getsize(path)
        self.assertGreaterEqual(size, 18 * 1024 * 1024)

        measurements = []
        for _ in range(_ITERATIONS):
            self.assertFalse(saw_terminal_command(iter_lines(path)))
            self.assertIsNone(parse_rate_limit_event(iter_lines(path)))
            measurements.append(_ru_maxrss_bytes())

        growth = measurements[-1] - measurements[1]
        self.assertLess(growth, _GROWTH_THRESHOLD_BYTES)


if __name__ == "__main__":
    unittest.main()
