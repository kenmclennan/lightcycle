import unittest

from lightcycle.domain.feedback import (
    LC_MARKER,
    outstanding_reviews,
    outstanding_threads,
    review_has_signal,
    thread_key,
)
from lightcycle.ports.github import Comment, Review


class TestOutstandingThreads(unittest.TestCase):
    def test_later_unmarked_reply_supersedes_earlier_one_in_same_thread(self):
        root = Comment(
            author="alice", body="please fix X and Y", is_top_level=False,
            id="c1", in_reply_to_id=None, created_at=1000.0,
        )
        reply = Comment(
            author="alice", body="actually scratch that, ignore X and Y", is_top_level=False,
            id="c2", in_reply_to_id="c1", created_at=2000.0,
        )

        self.assertEqual(outstanding_threads([root, reply]), [reply])

    def test_later_unmarked_reply_wins_regardless_of_input_order(self):
        root = Comment(
            author="alice", body="please fix X and Y", is_top_level=False,
            id="c1", in_reply_to_id=None, created_at=1000.0,
        )
        reply = Comment(
            author="alice", body="actually scratch that, ignore X and Y", is_top_level=False,
            id="c2", in_reply_to_id="c1", created_at=2000.0,
        )

        self.assertEqual(outstanding_threads([reply, root]), [reply])

    def test_a_marked_reply_does_not_clear_the_rest_of_its_thread(self):
        root = Comment(
            author="alice", body="please fix X and Y", is_top_level=False,
            id="c1", in_reply_to_id=None, created_at=1000.0,
        )
        marked_reply = Comment(
            author="bob", body=LC_MARKER + " done", is_top_level=False,
            id="c2", in_reply_to_id="c1", created_at=2000.0,
        )

        self.assertEqual(outstanding_threads([root, marked_reply]), [root])


class TestThreadKey(unittest.TestCase):
    def test_a_reply_keys_on_its_root(self):
        comment = Comment(
            author="alice", body="x", is_top_level=False,
            id="c2", in_reply_to_id="c1", created_at=1.0,
        )
        self.assertEqual(thread_key(comment), "c1")

    def test_a_root_comment_keys_on_itself(self):
        comment = Comment(
            author="alice", body="x", is_top_level=False,
            id="c1", in_reply_to_id=None, created_at=1.0,
        )
        self.assertEqual(thread_key(comment), "c1")


class TestReviewHasSignal(unittest.TestCase):
    def test_changes_requested_always_has_signal(self):
        review = Review(author="alice", body="", created_at=1.0, state="CHANGES_REQUESTED")
        self.assertTrue(review_has_signal(review))

    def test_commented_with_body_has_signal(self):
        review = Review(author="alice", body="looks off", created_at=1.0, state="COMMENTED")
        self.assertTrue(review_has_signal(review))

    def test_commented_without_body_has_no_signal(self):
        review = Review(author="alice", body="   ", created_at=1.0, state="COMMENTED")
        self.assertFalse(review_has_signal(review))

    def test_approved_has_no_signal(self):
        review = Review(author="alice", body="", created_at=1.0, state="APPROVED")
        self.assertFalse(review_has_signal(review))


class TestOutstandingReviews(unittest.TestCase):
    def test_a_review_with_signal_is_outstanding(self):
        review = Review(author="alice", body="", created_at=1.0, state="CHANGES_REQUESTED")

        self.assertEqual(outstanding_reviews([review]), [review])

    def test_a_review_marking_its_own_body_is_still_outstanding(self):
        review = Review(
            author="alice", body=LC_MARKER + " done", created_at=1.0, state="CHANGES_REQUESTED"
        )

        self.assertEqual(outstanding_reviews([review]), [review])

    def test_a_later_marked_comment_does_not_clear_an_earlier_review(self):
        review = Review(author="alice", body="", created_at=1.0, state="CHANGES_REQUESTED")

        self.assertEqual(outstanding_reviews([review]), [review])
