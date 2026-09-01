import unittest

from lightcycle.application.pool.breaker_status import (
    BreakerStatusResponse,
    BreakerStatusUseCase,
)


class FakeBreakerPort:
    def __init__(self, state=None):
        self._state = state or {}

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)


class TestBreakerStatusUseCase(unittest.TestCase):
    def test_closed_state(self):
        breaker_port = FakeBreakerPort(state={"open": False, "reset_at": None})
        result = BreakerStatusUseCase(breaker_port).execute(0)
        self.assertEqual(result, BreakerStatusResponse(is_open=False, reset_at=None, is_probing=False))

    def test_open_state(self):
        breaker_port = FakeBreakerPort(state={"open": True, "reset_at": 500})
        result = BreakerStatusUseCase(breaker_port).execute(0)
        self.assertEqual(result, BreakerStatusResponse(is_open=True, reset_at=500, is_probing=False))

    def test_not_cached_across_calls(self):
        breaker_port = FakeBreakerPort(state={"open": False, "reset_at": None})
        use_case = BreakerStatusUseCase(breaker_port)
        first = use_case.execute(0)
        self.assertEqual(first, BreakerStatusResponse(is_open=False, reset_at=None, is_probing=False))

        breaker_port.save({"open": True, "reset_at": 500})
        second = use_case.execute(0)
        self.assertEqual(second, BreakerStatusResponse(is_open=True, reset_at=500, is_probing=False))

    def test_missing_persisted_state_reads_as_closed(self):
        breaker_port = FakeBreakerPort()
        result = BreakerStatusUseCase(breaker_port).execute(0)
        self.assertEqual(result, BreakerStatusResponse(is_open=False, reset_at=None, is_probing=False))

    def test_never_saves(self):
        breaker_port = FakeBreakerPort(state={"open": False, "reset_at": None})
        saved = []
        breaker_port.save = lambda state: saved.append(state)
        BreakerStatusUseCase(breaker_port).execute(0)
        self.assertEqual(saved, [])


if __name__ == "__main__":
    unittest.main()
