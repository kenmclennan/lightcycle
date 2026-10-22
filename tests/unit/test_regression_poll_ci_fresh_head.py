import unittest

from lightcycle.domain.work import State
from lightcycle.ports.github import CheckRun
from tests.support.fake_fs import flow_from_metas
from tests.support.latent_github import LatentGitHub
from tests.support.pool_rig import PoolRig
from tests.support.sim_clock import SimClock
from tests.unit.test_resolve_ci import plant_pr

_URL = "https://github.com/x/y/pull/90"

_FLOW = flow_from_metas({
    "poller": {
        "engine": True,
        "step": "poll-ci",
        "routes": {"succeeded": "watch-ci", "failed": "watch-ci"},
        "on_ci_success": "succeeded",
        "on_ci_failure": "failed",
    },
    "watcher": {"model": "sonnet", "step": "watch-ci"},
})


class TestPollCiOnAFreshHead(unittest.TestCase):
    def test_a_head_whose_checks_register_late_is_not_judged_before_they_do(self):
        clock = SimClock()
        github = LatentGitHub(
            clock, head_shas={_URL: "sha1"}, base_keys={_URL: "x/y@main"},
            files_by_sha={(_URL, "sha1"): frozenset({"a.py"})})
        started = clock()
        github.workflow_run_appears(_URL, "sha1", after_seconds=20)
        github.check_runs_appear(
            _URL, "sha1", [CheckRun(name="build", status="completed", conclusion="success")],
            after_seconds=90)
        rig = PoolRig(_FLOW, clock=clock, github=github)
        item = rig.new_item("a fresh head")
        plant_pr(rig.store, item, _URL, branch="feat/thing")
        step = rig.store.create_step(stage="poll-ci", role="engine", item=item)
        early = []

        def finished():
            done = rig.store.get_node(step).state == State.DONE
            if done and clock() - started < 90:
                early.append(clock() - started)
            return done

        self.assertTrue(rig.run(400, every=5, until=finished))
        self.assertEqual(early, [])
        self.assertEqual(rig.store.get_node(step).outcome, "succeeded")
