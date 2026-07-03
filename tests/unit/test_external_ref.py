"""Unit tests for ExternalRef value object (pure, no IO)."""
import unittest

from the_grid.domain.work.external_ref import ExternalRef


class TestExternalRefShort(unittest.TestCase):

    def test_strips_prefix_and_dash(self):
        self.assertEqual(ExternalRef("proj", "proj-42.1").short, "42.1")

    def test_strips_hyphenated_prefix(self):
        self.assertEqual(ExternalRef("my-project", "my-project-7.2.3").short, "7.2.3")

    def test_passthrough_when_prefix_absent(self):
        self.assertEqual(ExternalRef("proj", "other-99").short, "other-99")

    def test_passthrough_plain_id(self):
        self.assertEqual(ExternalRef("proj", "99").short, "99")


class TestExternalRefQualify(unittest.TestCase):

    def test_adds_prefix_when_absent(self):
        self.assertEqual(ExternalRef.qualify("proj", "42.1"), "proj-42.1")

    def test_idempotent_when_already_qualified(self):
        self.assertEqual(ExternalRef.qualify("proj", "proj-42.1"), "proj-42.1")

    def test_idempotent_with_hyphenated_prefix(self):
        self.assertEqual(ExternalRef.qualify("my-project", "my-project-7.2.3"), "my-project-7.2.3")


class TestExternalRefRoundTrip(unittest.TestCase):

    def test_round_trip(self):
        prefix = "wkspc"
        bead_id = "wkspc-101.2.3"
        self.assertEqual(ExternalRef.qualify(prefix, ExternalRef(prefix, bead_id).short), bead_id)

    def test_round_trip_hyphenated_prefix(self):
        prefix = "the-grid"
        bead_id = "the-grid-707.4.1"
        self.assertEqual(ExternalRef.qualify(prefix, ExternalRef(prefix, bead_id).short), bead_id)


if __name__ == "__main__":
    unittest.main()
