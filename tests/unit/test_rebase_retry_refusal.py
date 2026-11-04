import json

import pytest

from lightcycle.application.flow.rebase_retries import checks_of
from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.rebase_retry_world import RebaseWorld

X = "describer / test"
Y = "describer / lint"


def line(check, prose="behind by 2"):
    return "rebase-retried: %s; %s" % (check, prose)


def test_first_retry_is_accepted():
    w = RebaseWorld()
    _step, rc, err = w.retry(line(X))
    assert rc == 0, err


def test_second_retry_on_the_same_check_is_refused_naming_step_check_and_failure():
    w = RebaseWorld()
    first, rc, _ = w.retry(line(X))
    assert rc == 0
    second = w.recheck()
    rc, _out, err = w.close(second, "retried", line(X))
    assert rc != 0
    assert first in err and X in err and "broke" in err
    assert w.store.get_node(second).state != State.DONE
    assert "outcome: retried" not in (w.store.get_node(second).notes or "")


def test_refusal_leaves_the_failure_outcome_closable():
    w = RebaseWorld()
    w.retry(line(X))
    second = w.recheck()
    w.close(second, "retried", line(X))
    rc, _out, err = w.close(second, "broke", "still failing")
    assert rc == 0, err


def test_retry_on_a_different_check_is_accepted():
    w = RebaseWorld()
    w.retry(line(X))
    _step, rc, err = w.retry(line(Y))
    assert rc == 0, err


def test_overlap_names_only_the_repeated_check_and_its_step():
    w = RebaseWorld()
    first, _rc, _err = w.retry(line(X))
    second = w.recheck()
    note = line(X) + "\n" + line(Y)
    rc, _out, err = w.close(second, "retried", note)
    assert rc != 0
    assert "check '%s' (step %s)" % (X, first) in err
    assert Y not in err


def test_retry_after_a_stale_reading_retry_is_accepted():
    w = RebaseWorld()
    w.retry("head moved from abc123 to def456")
    _step, rc, err = w.retry(line(X))
    assert rc == 0, err
    _step, rc, err = w.retry("head moved from def456 to 0a1b2c")
    assert rc == 0, err


def test_stale_reading_retry_after_a_check_naming_one_is_accepted():
    w = RebaseWorld()
    w.retry(line(X))
    _step, rc, err = w.retry("head moved from abc123 to def456")
    assert rc == 0, err


def test_new_phase_run_is_judged_against_that_run_only():
    w = RebaseWorld()
    w.retry(line(X))
    w.new_round()
    _step, rc, err = w.retry(line(X))
    assert rc == 0, err
    second = w.recheck()
    rc, _out, _err = w.close(second, "retried", line(X))
    assert rc != 0


def test_a_step_created_at_the_runs_opened_at_is_inside_the_window():
    w = RebaseWorld()
    stamp = w.store.get_run(w.run).opened_at
    w.store._now = lambda: stamp
    first, rc, _ = w.retry(line(X))
    assert rc == 0
    w.store._now = w._now
    second = w.recheck()
    rc, _out, err = w.close(second, "retried", line(X))
    assert rc != 0 and first in err


def test_failure_outcome_in_the_message_is_read_from_the_flow():
    w = RebaseWorld(failure_outcome="ci-failed")
    w.retry(line(X))
    second = w.recheck()
    _rc, _out, err = w.close(second, "retried", line(X))
    assert "ci-failed" in err and "broke" not in err


def test_a_stage_without_a_ci_failed_cap_accepts_the_repeat():
    w = RebaseWorld(with_cap=False)
    w.retry(line(X))
    _step, rc, err = w.retry(line(X))
    assert rc == 0, err


def test_repair_close_of_a_done_step_is_not_refused():
    w = RebaseWorld()
    first, _rc, _err = w.retry(line(X))
    w.retry(line(X))
    rc, _out, err = w.close(first, "retried", line(X))
    assert rc == 0, err


@pytest.mark.parametrize("note,expected", [
    ("rebase-retried: wf / job", ["wf / job"]),
    ("rebase-retried: a / b\nrebase-retried: c / d", ["a / b", "c / d"]),
    ("rebase-retried: wf / job; prose / more", ["wf / job"]),
    ("  Rebase-Retried:   wf / job  ", ["wf / job"]),
    ("wf-job / prose", ["wf-job"]),
    ("head moved from abc to def", []),
    ("", []),
    (None, []),
])
def test_checks_of(note, expected):
    assert checks_of(note) == expected


def _flow():
    return flow_from_metas({
        "ci": {"engine": True, "step": "ci", "routes": {"ok": "gate", "bad": "recheck"},
               "on_ci_success": "ok", "on_ci_failure": "bad"},
        "recheck": {"model": "sonnet", "step": "recheck",
                    "routes": {"again": "ci", "done": "gate"}},
        "gate": {"step": "gate", "routes": {"back": "open"}},
        "open": {"model": "sonnet", "step": "open", "routes": {"done": "ci"}},
    })


def test_rebase_retry_is_found_by_the_route_to_the_ci_stage():
    retry = _flow().rebase_retry("recheck")
    assert retry.retry_outcomes == frozenset({"again"})
    assert retry.failure_outcome is None


def test_other_stages_routing_into_the_ci_stage_are_not_rebase_retry():
    flow = _flow()
    assert flow.rebase_retry("ci") is None
    assert flow.rebase_retry("open") is None
    assert flow.rebase_retry("gate") is None


def test_claim_carries_rebase_retried_only_for_the_rebase_retry_stage():
    w = RebaseWorld()
    w.recheck()
    assert json.loads(w.claim_next())["rebase_retried"] == []
    w2 = RebaseWorld()
    w2.retry(line(X))
    w2.recheck()
    assert json.loads(w2.claim_next())["rebase_retried"] == [X]
    w3 = RebaseWorld()
    w3.store.create_step(stage="write", role="agent", item=w3.item)
    assert "rebase_retried" not in json.loads(w3.claim_next())
