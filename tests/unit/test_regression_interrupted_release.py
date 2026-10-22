import unittest

from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.latent_github import LatentGitHub
from tests.support.pool_crash import PoolCrash, crash_on
from tests.support.pool_rig import PoolRig
from tests.support.sim_clock import SimClock
from tests.unit.test_resolve_merged_prs import plant_pr

_URL = "https://github.com/x/y/pull/7"
_BRANCH = "feat/app-code-login"

_FLOW = flow_from_metas({
    "reviewer": {
        "step": "ready-merge",
        "phase": "code",
        "routes": {"merged": "cleanup"},
        "on_pr_merge": "merged",
    },
    "cleaner": {"model": "sonnet", "step": "cleanup", "phase": "code"},
})


class TestPoolStopInsideAPostMergeRelease(unittest.TestCase):
    def test_a_restarted_pool_finishes_the_half_removed_worktree(self):
        clock = SimClock()
        github = LatentGitHub(clock, head_shas={_URL: "sha1"}, base_keys={_URL: "x/y@main"})
        rig = PoolRig(_FLOW, clock=clock, github=github)
        item = rig.new_item("Login")
        run = plant_pr(rig.store, item, _URL, phase="code", branch=_BRANCH)
        gate = rig.store.create_step(stage="ready-merge", role="human", item=item)
        rig.seed_worktree(run)
        path = rig.worktrees.path_for_run(rig.store.get_run(run))
        github.merge(_URL)
        crash = crash_on(rig.git, "remove_worktree", when="after")

        with self.assertRaises(PoolCrash):
            rig.run(300, every=5)

        self.assertTrue(crash.fired)
        self.assertEqual(rig.store.get_run(run).state, "merged")
        self.assertEqual(rig.store.get_node(gate).state, State.DONE)
        self.assertFalse(rig.git.worktree_registered(rig.target, path))
        self.assertTrue(rig.git.branch_exists(rig.target, _BRANCH))

        rig.restart()
        rig.tick()

        self.assertFalse(rig.git.worktree_registered(rig.target, path))
        self.assertFalse(rig.git.branch_exists(rig.target, _BRANCH))
