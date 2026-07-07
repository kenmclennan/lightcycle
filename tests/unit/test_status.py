import unittest

from lightcycle.domain.work import Lane, Status


class TestStatusLane(unittest.TestCase):
    def test_every_status_maps_to_a_lane(self):
        for status in Status:
            self.assertIsInstance(status.lane, Lane)

    def test_the_mapping(self):
        self.assertEqual(Status.READY.lane, Lane.QUEUE)
        self.assertEqual(Status.IN_PROGRESS.lane, Lane.ACTIVE)
        self.assertEqual(Status.NEEDS_HUMAN.lane, Lane.INBOX)
        self.assertEqual(Status.DONE.lane, Lane.DONE)


if __name__ == "__main__":
    unittest.main()
