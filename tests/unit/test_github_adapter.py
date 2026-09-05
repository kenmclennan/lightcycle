import json
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.ports.github import ReadFailure

_PR = "https://github.com/x/y/pull/7"


def _proc(stdout="", returncode=0, stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _jq_arg(mock_run):
    args = mock_run.call_args.args[0]
    return args[args.index("--jq") + 1]


class TestReviews(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_parses_author_and_body_from_reviews_payload(self):
        payload = json.dumps(
            {
                "author": "copilot-pull-request-reviewer[bot]",
                "body": "found a bug on line 12",
                "created_at": 1704153600.0,
                "state": "COMMENTED",
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].author, "copilot-pull-request-reviewer[bot]")
        self.assertEqual(reviews[0].body, "found a bug on line 12")
        self.assertGreater(reviews[0].created_at, 0.0)
        self.assertEqual(reviews[0].state, "COMMENTED")

    def test_parses_changes_requested_state(self):
        payload = json.dumps(
            {
                "author": "reviewer",
                "body": "please fix this",
                "created_at": 1704153600.0,
                "state": "CHANGES_REQUESTED",
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(reviews[0].state, "CHANGES_REQUESTED")

    def test_defaults_state_to_empty_string_when_absent(self):
        payload = json.dumps(
            {
                "author": "reviewer",
                "body": "no state field here",
                "created_at": 1704153600.0,
                "state": None,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(reviews[0].state, "")

    def test_multiple_reviews_parsed_from_ndjson_lines(self):
        payload = "\n".join(
            json.dumps(
                {
                    "author": "reviewer-%d" % i,
                    "body": "review %d" % i,
                    "created_at": 1704153600.0 + i,
                    "state": "COMMENTED",
                }
            )
            for i in range(3)
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(len(reviews), 3)
        self.assertEqual([r.author for r in reviews], ["reviewer-0", "reviewer-1", "reviewer-2"])

    def test_since_cutoff_is_embedded_in_constructed_jq(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.reviews(_PR, since=9999999999.0)

        jq = _jq_arg(mock_run)
        self.assertIn("9999999999.0", jq)
        self.assertIn("submitted_at", jq)

    def test_constructed_jq_projects_only_read_fields(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.reviews(_PR, since=0.0)

        jq = _jq_arg(mock_run)
        for field in ("author", "body", "state", "created_at"):
            self.assertIn(field, jq)

    def test_tolerates_pending_review_without_submitted_at(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.reviews(_PR, since=0.0)

        jq = _jq_arg(mock_run)
        self.assertIn('.submitted_at // "1970-01-01T00:00:00Z"', jq)

    def test_command_failure_returns_a_distinguishable_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("", returncode=1, stderr="gh: bad jq filter"),
        ):
            reviews = self.adapter.reviews(_PR, since=0.0)

        self.assertEqual(reviews, ReadFailure(1, "gh: bad jq filter"))

    def test_non_pr_url_returns_empty_list(self):
        reviews = self.adapter.reviews("not-a-pr-url", since=0.0)

        self.assertEqual(reviews, [])


class TestPullComments(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_parses_inline_comment_with_path_and_line(self):
        payload = json.dumps(
            {
                "author": "reviewer",
                "body": "nit: rename this",
                "created_at": 1704153600.0,
                "path": "src/foo.py",
                "line": 42,
                "id": None,
                "in_reply_to_id": None,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(len(comments), 1)
        self.assertFalse(comments[0].is_top_level)
        self.assertEqual(comments[0].path, "src/foo.py")
        self.assertEqual(comments[0].line, 42)

    def test_parses_id_reply_link_and_created_at(self):
        payload = json.dumps(
            {
                "id": 111,
                "in_reply_to_id": 100,
                "author": "reviewer",
                "body": "nit: rename this",
                "created_at": 1704153600.0,
                "path": "src/foo.py",
                "line": 42,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(comments[0].id, "111")
        self.assertEqual(comments[0].in_reply_to_id, "100")
        self.assertGreater(comments[0].created_at, 0.0)

    def test_root_comment_has_no_in_reply_to_id(self):
        payload = json.dumps(
            {
                "id": 100,
                "in_reply_to_id": None,
                "author": "reviewer",
                "body": "nit: rename this",
                "created_at": 1704153600.0,
                "path": "src/foo.py",
                "line": 42,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(comments[0].id, "100")
        self.assertIsNone(comments[0].in_reply_to_id)

    def test_multiple_comments_parsed_from_ndjson_lines(self):
        payload = "\n".join(
            json.dumps(
                {
                    "id": i,
                    "in_reply_to_id": None,
                    "author": "reviewer",
                    "body": "comment %d" % i,
                    "created_at": 1704153600.0 + i,
                    "path": "src/foo.py",
                    "line": i,
                }
            )
            for i in range(3)
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(len(comments), 3)
        self.assertEqual([c.id for c in comments], ["0", "1", "2"])

    def test_since_cutoff_is_embedded_in_constructed_jq(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.pull_comments(_PR, since=9999999999.0)

        jq = _jq_arg(mock_run)
        self.assertIn("9999999999.0", jq)
        self.assertIn("created_at", jq)

    def test_constructed_jq_projects_only_read_fields(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.pull_comments(_PR, since=0.0)

        jq = _jq_arg(mock_run)
        for field in ("author", "body", "id", "in_reply_to_id", "path", "line", "created_at"):
            self.assertIn(field, jq)

    def test_command_failure_returns_a_distinguishable_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("", returncode=1, stderr="gh: bad jq filter"),
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(comments, ReadFailure(1, "gh: bad jq filter"))

    def test_non_pr_url_returns_empty_list(self):
        comments = self.adapter.pull_comments("not-a-pr-url", since=0.0)

        self.assertEqual(comments, [])


class TestComments(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_parses_top_level_comment_with_id_and_created_at(self):
        payload = json.dumps(
            {
                "id": 200,
                "author": "reviewer",
                "body": "@lc please fix this",
                "created_at": 1704153600.0,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.comments_since(_PR, since=0.0)

        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0].is_top_level)
        self.assertEqual(comments[0].id, "200")
        self.assertIsNone(comments[0].in_reply_to_id)
        self.assertGreater(comments[0].created_at, 0.0)

    def test_defaults_author_and_body_to_empty_string_when_null(self):
        payload = json.dumps(
            {
                "id": 201,
                "author": None,
                "body": None,
                "created_at": 1704153600.0,
            }
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.comments_since(_PR, since=0.0)

        self.assertEqual(comments[0].author, "")
        self.assertEqual(comments[0].body, "")

    def test_multiple_comments_parsed_from_ndjson_lines(self):
        payload = "\n".join(
            json.dumps(
                {
                    "id": i,
                    "author": "reviewer",
                    "body": "comment %d" % i,
                    "created_at": 1704153600.0 + i,
                }
            )
            for i in range(3)
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.comments_since(_PR, since=0.0)

        self.assertEqual(len(comments), 3)
        self.assertEqual([c.id for c in comments], ["0", "1", "2"])

    def test_since_cutoff_is_embedded_in_constructed_jq(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.comments_since(_PR, since=9999999999.0)

        jq = _jq_arg(mock_run)
        self.assertIn("9999999999.0", jq)
        self.assertIn("created_at", jq)

    def test_constructed_jq_projects_only_read_fields(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.comments_since(_PR, since=0.0)

        jq = _jq_arg(mock_run)
        for field in ("author", "body", "id", "created_at"):
            self.assertIn(field, jq)

    def test_command_failure_returns_a_distinguishable_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("", returncode=1, stderr="gh: bad jq filter"),
        ):
            comments = self.adapter.comments_since(_PR, since=0.0)

        self.assertEqual(comments, ReadFailure(1, "gh: bad jq filter"))

    def test_non_pr_url_returns_empty_list(self):
        comments = self.adapter.comments_since("not-a-pr-url", since=0.0)

        self.assertEqual(comments, [])


class TestLastPushTime(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_constructed_jq_requests_only_committer_date(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ) as mock_run:
            self.adapter.last_push_time(_PR)

        args = mock_run.call_args.args[0]
        jq = _jq_arg(mock_run)
        self.assertEqual(jq, ".[-1].commit.committer.date // empty")
        self.assertNotIn("-r", args)

    def test_populated_commit_returns_parsed_timestamp(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("2024-01-02T00:00:00Z\n"),
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertGreater(result, 0.0)

    def test_no_commits_returns_zero(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertEqual(result, 0.0)

    def test_command_failure_returns_a_distinguishable_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("", returncode=1, stderr="gh: auth error"),
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_non_pr_url_returns_zero(self):
        result = self.adapter.last_push_time("not-a-pr-url")

        self.assertEqual(result, 0.0)


class TestChangedFiles(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _mock_run(self, compare_stdout):
        pr_view = _proc(json.dumps({"baseRefName": "main"}))
        compare = _proc(compare_stdout)
        return MagicMock(side_effect=[pr_view, compare])

    def test_constructed_jq_requests_only_filenames(self):
        mock_run = self._mock_run("[]")
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            self.adapter.changed_files(_PR, "abc123")

        compare_call = mock_run.call_args_list[1]
        jq = compare_call.args[0][compare_call.args[0].index("--jq") + 1]
        self.assertIn("filename", jq)
        self.assertNotIn("patch", jq)

    def test_populated_files_returns_matching_frozenset(self):
        mock_run = self._mock_run(json.dumps(["src/a.py", "src/b.py"]))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertEqual(files, frozenset({"src/a.py", "src/b.py"}))

    def test_no_files_key_returns_empty_frozenset(self):
        mock_run = self._mock_run("[]")
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertEqual(files, frozenset())

    def test_compare_call_failure_returns_a_distinguishable_read_failure(self):
        pr_view = _proc(json.dumps({"baseRefName": "main"}))
        compare = _proc("", returncode=1, stderr="gh: bad jq filter")
        mock_run = MagicMock(side_effect=[pr_view, compare])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertEqual(files, ReadFailure(1, "gh: bad jq filter"))

    def test_pr_view_call_failure_returns_a_distinguishable_read_failure(self):
        pr_view = _proc("", returncode=1, stderr="gh: auth error")
        mock_run = MagicMock(side_effect=[pr_view])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertEqual(files, ReadFailure(1, "gh: auth error"))

    def test_non_pr_url_returns_empty_frozenset(self):
        files = self.adapter.changed_files("not-a-pr-url", "abc123")

        self.assertEqual(files, frozenset())


class TestCiPending(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _run(self, payload):
        return MagicMock(return_value=_proc(json.dumps(payload)))

    def test_matching_sha_all_completed_is_not_pending(self):
        mock_run = self._run({
            "headRefOid": "sha1",
            "statusCheckRollup": [
                {"status": "COMPLETED", "conclusion": "SUCCESS"},
                {"status": "COMPLETED", "conclusion": "FAILURE"},
            ],
        })
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertFalse(pending)

    def test_matching_sha_with_in_progress_check_is_pending(self):
        mock_run = self._run({
            "headRefOid": "sha1",
            "statusCheckRollup": [
                {"status": "COMPLETED", "conclusion": "SUCCESS"},
                {"status": "IN_PROGRESS"},
            ],
        })
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertTrue(pending)

    def test_empty_rollup_is_pending(self):
        mock_run = self._run({"headRefOid": "sha1", "statusCheckRollup": []})
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertTrue(pending)

    def test_mismatched_head_sha_is_pending(self):
        mock_run = self._run({
            "headRefOid": "sha2",
            "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
        })
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertTrue(pending)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertEqual(pending, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            pending = self.adapter.ci_pending(_PR, "sha1")

        self.assertIsInstance(pending, ReadFailure)


if __name__ == "__main__":
    unittest.main()
