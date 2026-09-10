import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import ParkInput, ParkStepUseCase
from tests.support.fake_store import FakeStore
from tests.support.sqlite_store_factory import make_sqlite_store
from tests.support.step_factory import create_owned_step


class TestParkTask(unittest.TestCase):
    def test_empty_observation_raises(self):
        s = FakeStore()
        bid = create_owned_step(s, "build: x", step="build", role="agent")
        with self.assertRaises(UseCaseError):
            ParkStepUseCase(s).execute(
                ParkInput(step=bid, observation="  ", decision="decide X")
            )

    def test_empty_decision_raises(self):
        s = FakeStore()
        bid = create_owned_step(s, "build: x", step="build", role="agent")
        with self.assertRaises(UseCaseError):
            ParkStepUseCase(s).execute(
                ParkInput(step=bid, observation="something happened", decision="")
            )

    def test_park_sets_needs_reason_role_and_note_on_fake_store(self):
        s = FakeStore()
        bid = create_owned_step(s, "build: x", step="build", role="agent")
        ParkStepUseCase(s).execute(
            ParkInput(step=bid, observation="something happened", decision="decide X")
        )
        t = s.get_node(bid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.park.needs, "decide X")
        self.assertEqual(t.park.reason, "something happened")
        self.assertTrue((t.notes or "").startswith("BLOCKED: decide X"))

    def test_park_sets_needs_reason_role_and_note_on_sqlite_store(self):
        s = make_sqlite_store()
        bid = create_owned_step(s, "build: x", step="build", role="agent")
        ParkStepUseCase(s).execute(
            ParkInput(step=bid, observation="something happened", decision="decide X")
        )
        t = s.get_node(bid)
        self.assertEqual(t.role, "human")
        self.assertEqual(t.park.needs, "decide X")
        self.assertEqual(t.park.reason, "something happened")
        self.assertTrue((t.notes or "").startswith("BLOCKED: decide X"))

    def test_park_carries_resume_fields_when_present(self):
        s = FakeStore()
        bid = create_owned_step(s, "build: x", step="build", role="agent")
        ParkStepUseCase(s).execute(
            ParkInput(
                step=bid, observation="something happened", decision="decide X",
                tried="a,b",
            )
        )
        self.assertEqual(s.get_node(bid).park.tried, "a,b")

    def test_a_failing_reassign_leaves_the_metadata_write_unapplied(self):
        s = FakeStore()
        bid = create_owned_step(s, "build: x", step="build", role="agent")

        def raising_reassign(tid, role):
            raise RuntimeError("boom")

        s.reassign = raising_reassign
        with self.assertRaises(RuntimeError):
            ParkStepUseCase(s).execute(
                ParkInput(step=bid, observation="something happened", decision="decide X")
            )
        t = s.get_node(bid)
        self.assertIsNone(t.park.needs)
        self.assertIsNone(t.park.reason)
        self.assertEqual(t.role, "agent")


if __name__ == "__main__":
    unittest.main()
