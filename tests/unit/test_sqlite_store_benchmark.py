import time
import unittest

from tests.support.sqlite_store_factory import make_sqlite_store

_ITERATIONS = 25
_BATCH_ITERATIONS = 21
_CALIBRATION_UNIT = 2000
_SINGLE_OP_MAX_RATIO = 30.0
_BATCH_500_MAX_RATIO = 1500.0


def _median_ms(fn, iterations=_ITERATIONS):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    return times[len(times) // 2]


def _calibration_ms():
    x = 0
    for i in range(_CALIBRATION_UNIT):
        x += i
    return x


def _assert_ratio_within(test_case, op_name, elapsed_ms, calibration_ms, max_ratio):
    ratio = elapsed_ms / calibration_ms
    test_case.assertLessEqual(
        ratio,
        max_ratio,
        "%s took %.3fms (%.1fx calibration %.3fms, max %.1fx)"
        % (op_name, elapsed_ms, ratio, calibration_ms, max_ratio),
    )


class TestSqliteStoreBenchmark(unittest.TestCase):
    def test_create_is_fast_relative_to_calibration(self):
        s = make_sqlite_store()
        counter = iter(range(_ITERATIONS))
        elapsed = _median_ms(lambda: s.create_step("t%d" % next(counter), role="coder"))
        calibration = _median_ms(_calibration_ms)
        _assert_ratio_within(self, "create_step", elapsed, calibration, _SINGLE_OP_MAX_RATIO)

    def test_close_is_fast_relative_to_calibration(self):
        s = make_sqlite_store()
        ids = iter([s.create_step("t%d" % i, role="coder") for i in range(_ITERATIONS)])
        elapsed = _median_ms(lambda: s.close(next(ids), "done"))
        calibration = _median_ms(_calibration_ms)
        _assert_ratio_within(self, "close", elapsed, calibration, _SINGLE_OP_MAX_RATIO)

    def test_all_nodes_over_500_is_fast_relative_to_calibration(self):
        s = make_sqlite_store()
        for i in range(500):
            s.create_step("t%d" % i, role="coder")
        elapsed = _median_ms(lambda: s.all_nodes(), iterations=_BATCH_ITERATIONS)
        calibration = _median_ms(_calibration_ms)
        _assert_ratio_within(self, "all_nodes", elapsed, calibration, _BATCH_500_MAX_RATIO)

    def test_ready_steps_over_500_is_fast_relative_to_calibration(self):
        s = make_sqlite_store()
        for i in range(500):
            s.create_step("t%d" % i, role="coder")
        elapsed = _median_ms(lambda: s.ready_steps(), iterations=_BATCH_ITERATIONS)
        calibration = _median_ms(_calibration_ms)
        _assert_ratio_within(self, "ready_steps", elapsed, calibration, _BATCH_500_MAX_RATIO)

    def test_ratio_assertion_fails_on_injected_slowdown(self):
        def _slow_op():
            time.sleep(0.02)

        elapsed = _median_ms(_slow_op, iterations=3)
        calibration = _median_ms(_calibration_ms)
        with self.assertRaises(AssertionError):
            _assert_ratio_within(self, "synthetic_op", elapsed, calibration, _SINGLE_OP_MAX_RATIO)


if __name__ == "__main__":
    unittest.main()
