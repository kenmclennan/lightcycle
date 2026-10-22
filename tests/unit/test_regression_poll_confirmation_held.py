import unittest

from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.latent_github import LatentGitHub
from tests.support.pool_rig import PoolRig
from tests.support.sim_clock import SimClock
from tests.unit.test_resolve_ci import plant_pr

_FIRST = "https://github.com/x/y/pull/1"
_SECOND = "https://github.com/x/y/pull/2"

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


class TestAwaitedPrKeepsItsConfirmation(unittest.TestCase):
    def test_a_poll_that_asks_about_another_pr_keeps_the_awaited_prs_confirmation(self):
        clock = SimClock()
        github = LatentGitHub(
            clock, head_shas={_FIRST: "sha1", _SECOND: "sha2"},
            base_keys={_FIRST: "x/y@main", _SECOND: "x/y@main"})
        rig = PoolRig(_FLOW, clock=clock, github=github, stepped_poll=True)
        steps = {}
        for url in (_FIRST, _SECOND):
            item = rig.new_item("PR %s" % url)
            plant_pr(rig.store, item, url, branch="feat/%s" % url[-1])
            steps[url] = rig.store.create_step(stage="poll-ci", role="engine", item=item)
        first_sight = rig.snapshot.poll_epoch()

        rig.tick()
        rig.release_poll()

        self.assertTrue(rig.snapshot.confirmed_after(_FIRST, first_sight))

        rig.poll_between_ticks(after=60, reads=[_SECOND])

        self.assertTrue(rig.snapshot.confirmed_after(_FIRST, first_sight))
        self.assertEqual(rig.store.get_node(steps[_FIRST]).state, State.QUEUED)
