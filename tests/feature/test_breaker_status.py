import pytest
from pytest_bdd import given, scenarios, then, when

from lightcycle.application.pool.breaker_status import BreakerStatusUseCase

scenarios("breaker-status.feature")


class FakeBreakerPort:
    def __init__(self, state=None):
        self._state = state or {}
        self.save_calls = []

    def load(self):
        return dict(self._state)

    def save(self, state):
        self.save_calls.append(dict(state))
        self._state = dict(state)


@pytest.fixture
def ctx():
    return {}


@given("a breaker status use case backed by a breaker port")
def _use_case(ctx):
    ctx["breaker_port"] = FakeBreakerPort()
    ctx["use_case"] = BreakerStatusUseCase(ctx["breaker_port"])


@given("the breaker's persisted state is closed")
def _closed(ctx):
    ctx["breaker_port"].save({"open": False, "reset_at": None})


@given("the breaker's persisted state is open with a reset time")
def _open_with_reset_time(ctx):
    ctx["reset_at"] = 500
    ctx["breaker_port"].save({"open": True, "reset_at": 500})


@given("the breaker has no persisted state")
def _no_persisted_state(ctx):
    pass


@given("the breaker status has already been read once")
def _read_once(ctx):
    ctx["use_case"].execute()


@when("the breaker's persisted state changes to open with a reset time")
def _changes_to_open(ctx):
    ctx["reset_at"] = 500
    ctx["breaker_port"].save({"open": True, "reset_at": 500})


@when("the breaker status is read")
@when("the breaker status is read again")
def _read(ctx):
    before = len(ctx["breaker_port"].save_calls)
    ctx["result"] = ctx["use_case"].execute()
    ctx["saves_during_read"] = len(ctx["breaker_port"].save_calls) - before


@then("the status is closed")
def _status_is_closed(ctx):
    assert ctx["result"].is_open is False


@then("the status is open with that reset time")
def _status_is_open_with_reset_time(ctx):
    assert ctx["result"].is_open is True
    assert ctx["result"].reset_at == ctx["reset_at"]


@then("the breaker port was never saved to")
def _never_saved_to(ctx):
    assert ctx["saves_during_read"] == 0
