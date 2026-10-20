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


def _linked(review_id):
    return Comment(
        author="alice", body="nit", is_top_level=False, id="c-" + review_id,
        path="a.py", line=1, created_at=1.0, review_id=review_id,
    )


class TestOutstandingReviews(unittest.TestCase):
    def test_a_review_with_signal_and_a_linked_inline_comment_is_outstanding(self):
        review = Review(
            author="alice", body="", created_at=1.0, state="CHANGES_REQUESTED", id="r1"
        )

        self.assertEqual(outstanding_reviews([review], [_linked("r1")], "@lc"), [review])

    def test_a_review_marking_its_own_body_is_still_outstanding_when_linked(self):
        review = Review(
            author="alice", body=LC_MARKER + " done", created_at=1.0,
            state="CHANGES_REQUESTED", id="r1",
        )

        self.assertEqual(outstanding_reviews([review], [_linked("r1")], "@lc"), [review])

    def test_a_marker_bodied_review_without_token_or_link_is_dropped(self):
        review = Review(
            author="alice", body=LC_MARKER + " done", created_at=1.0,
            state="CHANGES_REQUESTED", id="r1",
        )

        self.assertEqual(outstanding_reviews([review], [], "@lc"), [])

    def test_only_reviews_with_a_link_or_the_token_are_admitted(self):
        linked = Review(author="a", body="see inline", created_at=1.0, state="COMMENTED", id="r1")
        tokened = Review(author="a", body="@lc fix", created_at=1.0, state="COMMENTED", id="r2")
        neither = Review(author="a", body="all good", created_at=1.0, state="COMMENTED", id="r3")
        empty = Review(author="a", body="", created_at=1.0, state="CHANGES_REQUESTED", id="r4")
        no_id = Review(author="a", body="see inline", created_at=1.0, state="COMMENTED", id=None)

        result = outstanding_reviews(
            [linked, tokened, neither, empty, no_id], [_linked("r1")], "@lc"
        )

        self.assertEqual(result, [linked, tokened])

    def test_without_a_mention_token_only_a_linked_review_is_admitted(self):
        linked = Review(author="a", body="see inline", created_at=1.0, state="COMMENTED", id="r1")
        tokened = Review(author="a", body="@lc fix", created_at=1.0, state="COMMENTED", id="r2")

        result = outstanding_reviews([linked, tokened], [_linked("r1")], None)

        self.assertEqual(result, [linked])
