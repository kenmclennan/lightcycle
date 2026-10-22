import unittest

from lightcycle.domain.work import State
from tests.support.fake_fs import flow_from_metas
from tests.support.latent_github import LatentGitHub
from tests.support.pool_rig import PoolRig
from tests.support.sim_clock import SimClock
from tests.unit.test_resolve_merged_prs import plant_pr

_FIRST = "https://github.com/x/y/pull/1"
_SECOND = "https://github.com/x/y/pull/2"

_FLOW = flow_from_metas({
    "amender": {
        "model": "sonnet", "step": "amend", "phase": "amend",
        "routes": {"done": "ready-merge"},
    },
    "reviewer": {
        "step": "ready-merge",
        "phase": "amend",
        "routes": {"merged": "amend"},
        "on_pr_merge": "merged",
    },
})


class TestSecondAmendRound(unittest.TestCase):
    def test_a_merged_first_round_does_not_stand_in_for_the_second(self):
        clock = SimClock()
        github = LatentGitHub(
            clock, head_shas={_FIRST: "sha1", _SECOND: "sha2"},
            base_keys={_FIRST: "x/y@main", _SECOND: "x/y@main"})
        rig = PoolRig(_FLOW, clock=clock, github=github)
        item = rig.new_item("Amend")
        plant_pr(rig.store, item, _FIRST, phase="amend", branch="feat/app-amend")
        first_gate = rig.store.create_step(stage="ready-merge", role="human", item=item)
        github.merge(_FIRST)

        self.assertTrue(rig.run(300, every=5, until=lambda: (
            rig.store.get_node(first_gate).state == State.DONE)))

        amend = [s for s in rig.store.all_steps() if s.stage == "amend"][0]
        rig.worktrees.ensure(amend)
        second_run = rig.store.current_run(item, "amend")
        self.assertIsNotNone(second_run)
        self.assertTrue(second_run.is_open)
        self.assertNotEqual(second_run.pr, _FIRST)
        rig.store.set_pr(second_run.id, _SECOND)
        second_gate = rig.store.create_step(stage="ready-merge", role="human", item=item)

        rig.run(120, every=5)

        self.assertNotEqual(rig.store.get_node(second_gate).state, State.DONE)

        github.merge(_SECOND)

        self.assertTrue(rig.run(300, every=5, until=lambda: (
            rig.store.get_node(second_gate).state == State.DONE)))
