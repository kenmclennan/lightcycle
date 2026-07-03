import time
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store

_SINGLE_OP_MAX_MS = 1.0
_BATCH_500_MAX_MS = 20.0
_ITERATIONS = 25


def _median_ms(fn, iterations=_ITERATIONS):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return times[len(times) // 2]


class TestSqliteStoreBenchmark(unittest.TestCase):
    def test_create_is_sub_millisecond(self):
        s = make_sqlite_store()
        counter = iter(range(_ITERATIONS))
        elapsed = _median_ms(lambda: s.create_task("t%d" % next(counter), role="coder"))
        self.assertLess(elapsed, _SINGLE_OP_MAX_MS, "create_task took %.3fms" % elapsed)

    def test_close_is_sub_millisecond(self):
        s = make_sqlite_store()
        ids = iter([s.create_task("t%d" % i, role="coder") for i in range(_ITERATIONS)])
        elapsed = _median_ms(lambda: s.close(next(ids), "done"))
        self.assertLess(elapsed, _SINGLE_OP_MAX_MS, "close took %.3fms" % elapsed)

    def test_list_all_of_500_is_a_few_milliseconds(self):
        s = make_sqlite_store()
        for i in range(500):
            s.create_task("t%d" % i, role="coder")
        elapsed = _median_ms(lambda: s.all_tasks(), iterations=5)
        self.assertLess(elapsed, _BATCH_500_MAX_MS, "all_tasks took %.3fms" % elapsed)

    def test_ready_query_over_500_is_a_few_milliseconds(self):
        s = make_sqlite_store()
        for i in range(500):
            s.create_task("t%d" % i, role="coder")
        elapsed = _median_ms(lambda: s.ready_tasks(), iterations=5)
        self.assertLess(elapsed, _BATCH_500_MAX_MS, "ready_tasks took %.3fms" % elapsed)


if __name__ == "__main__":
    unittest.main()
