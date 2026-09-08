import datetime

from pytest_bdd import given, parsers, scenarios, then, when

from lightcycle.domain.feedback import Duration
from lightcycle.domain.work import State

scenarios("duration-elapsed-since-claim.feature")


@given("a duration computed from a step's history transitions", target_fixture="ctx")
def _ctx():
    return {}


@given(parsers.parse(
    'the history has a RUNNING transition at "{ts}" and no DONE transition'
))
def _running_only(ctx, ts):
    ctx["transitions"] = [(State.RUNNING, ts)]


@given("the history has only a WAITING transition and no RUNNING transition")
def _waiting_only(ctx):
    ctx["transitions"] = [(State.WAITING, "2026-01-01T10:00:00")]


@given(parsers.parse(
    'the history has a RUNNING transition at "{claimed_ts}" and a DONE transition at "{done_ts}"'
))
def _running_and_done(ctx, claimed_ts, done_ts):
    ctx["transitions"] = [
        (State.RUNNING, claimed_ts),
        (State.DONE, done_ts),
    ]


@given(parsers.parse(
    'the history has a RUNNING transition at "{first_ts}", then a WAITING transition, '
    'then a second RUNNING transition at "{second_ts}", and no DONE transition'
))
def _reworked_still_active(ctx, first_ts, second_ts):
    ctx["transitions"] = [
        (State.RUNNING, first_ts),
        (State.WAITING, first_ts),
        (State.RUNNING, second_ts),
    ]


@given("the history has a RUNNING transition with no timestamp and no DONE transition")
def _missing_claim_timestamp(ctx):
    ctx["transitions"] = [(State.RUNNING, None)]


@when(parsers.parse('elapsed_since_claim is computed with now "{now}"'))
def _compute_elapsed_since_claim(ctx, now):
    ctx["result"] = Duration(ctx["transitions"]).elapsed_since_claim(now)


@when("elapsed is computed")
def _compute_elapsed(ctx):
    ctx["result"] = Duration(ctx["transitions"]).elapsed()


@then(parsers.parse("the elapsed duration is {minutes:d} minutes"))
def _assert_minutes(ctx, minutes):
    assert ctx["result"] == datetime.timedelta(minutes=minutes)


@then(parsers.parse("the elapsed duration is {hours:d} hour {minutes:d} minutes"))
def _assert_hours_minutes(ctx, hours, minutes):
    assert ctx["result"] == datetime.timedelta(hours=hours, minutes=minutes)


@then("the elapsed duration is unknown")
def _assert_unknown(ctx):
    assert ctx["result"] is None
