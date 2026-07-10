import json
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters.github import GitHubEventsAdapter

_PR = "https://github.com/x/y/pull/7"


def _proc(stdout="", returncode=0):
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


class TestReviews(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_parses_author_and_body_from_reviews_payload(self):
        payload = json.dumps(
            [
                {
                    "user": {"login": "copilot-pull-request-reviewer[bot]"},
                    "body": "found a bug on line 12",
                    "submitted_at": "2024-01-02T00:00:00Z",
                }
            ]
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].author, "copilot-pull-request-reviewer[bot]")
        self.assertEqual(reviews[0].body, "found a bug on line 12")

    def test_excludes_reviews_submitted_before_since(self):
        payload = json.dumps(
            [
                {
                    "user": {"login": "reviewer"},
                    "body": "old review",
                    "submitted_at": "2024-01-01T00:00:00Z",
                }
            ]
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=9999999999.0)

        self.assertEqual(reviews, [])

    def test_tolerates_pending_review_without_submitted_at(self):
        payload = json.dumps(
            [
                {
                    "user": {"login": "reviewer"},
                    "body": "still drafting",
                    "submitted_at": None,
                }
            ]
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(reviews, [])

    def test_command_failure_returns_empty_list(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("", returncode=1)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(reviews, [])

    def test_non_pr_url_returns_empty_list(self):
        reviews = self.adapter.reviews("not-a-pr-url", since=0.0)

        self.assertEqual(reviews, [])


class TestPullComments(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_parses_inline_comment_with_path_and_line(self):
        payload = json.dumps(
            [
                {
                    "user": {"login": "reviewer"},
                    "body": "nit: rename this",
                    "created_at": "2024-01-02T00:00:00Z",
                    "path": "src/foo.py",
                    "line": 42,
                }
            ]
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(len(comments), 1)
        self.assertFalse(comments[0].is_top_level)
        self.assertEqual(comments[0].path, "src/foo.py")
        self.assertEqual(comments[0].line, 42)

    def test_excludes_comments_created_before_since(self):
        payload = json.dumps(
            [
                {
                    "user": {"login": "reviewer"},
                    "body": "old comment",
                    "created_at": "2024-01-01T00:00:00Z",
                    "path": "src/foo.py",
                    "line": 1,
                }
            ]
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=9999999999.0)

        self.assertEqual(comments, [])

    def test_command_failure_returns_empty_list(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("", returncode=1)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(comments, [])

    def test_non_pr_url_returns_empty_list(self):
        comments = self.adapter.pull_comments("not-a-pr-url", since=0.0)

        self.assertEqual(comments, [])


if __name__ == "__main__":
    unittest.main()
