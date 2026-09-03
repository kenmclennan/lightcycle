import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import ParkInput, ParkStepUseCase
from tests.support.fake_store import FakeStore
from tests.support.sqlite_store_factory import make_sqlite_store


class TestParkTask(unittest.TestCase):
    def test_empty_observation_raises(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="agent")
        with self.assertRaises(UseCaseError):
            ParkStepUseCase(s).execute(
                ParkInput(step=bid, observation="  ", decision="decide X")
            )

    def test_empty_decision_raises(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="agent")
        with self.assertRaises(UseCaseError):
            ParkStepUseCase(s).execute(
                ParkInput(step=bid, observation="something happened", decision="")
            )

    def test_park_sets_needs_reason_role_and_note_on_fake_store(self):
        s = FakeStore()
        bid = s.create_step("build: x", step="build", role="agent")
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
        bid = s.create_step("build: x", step="build", role="agent")
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
        bid = s.create_step("build: x", step="build", role="agent")
        ParkStepUseCase(s).execute(
            ParkInput(
                step=bid, observation="something happened", decision="decide X",
                branch="feat/y", pr="123", tried="a,b",
            )
        )
        t = s.get_node(bid)
        self.assertEqual(t.branch, "feat/y")
        self.assertEqual(t.pr, "123")
        self.assertEqual(t.park.tried, "a,b")


if __name__ == "__main__":
    unittest.main()
