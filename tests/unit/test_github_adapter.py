import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters.github import GitHubEventsAdapter
from lightcycle.ports.github import CheckRun, PrSync, RateLimit, ReadFailure

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

    def test_non_pr_url_returns_read_failure(self):
        reviews = self.adapter.reviews("not-a-pr-url", since=0.0)

        self.assertIsInstance(reviews, ReadFailure)


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

    def test_pull_request_review_id_is_parsed_as_a_string(self):
        payload = json.dumps(
            {"id": 100, "author": "reviewer", "body": "nit", "created_at": 1704153600.0,
             "pull_request_review_id": 555}
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertEqual(comments[0].review_id, "555")

    def test_missing_pull_request_review_id_yields_none(self):
        payload = json.dumps(
            {"id": 100, "author": "reviewer", "body": "nit", "created_at": 1704153600.0}
        )
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc(payload)
        ):
            comments = self.adapter.pull_comments(_PR, since=0.0)

        self.assertIsNone(comments[0].review_id)

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

    def test_non_pr_url_returns_read_failure(self):
        comments = self.adapter.pull_comments("not-a-pr-url", since=0.0)

        self.assertIsInstance(comments, ReadFailure)


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

    def test_non_pr_url_returns_read_failure(self):
        comments = self.adapter.comments_since("not-a-pr-url", since=0.0)

        self.assertIsInstance(comments, ReadFailure)


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

    def test_no_commits_returns_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run", return_value=_proc("")
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_unparseable_date_returns_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("not-a-date\n"),
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_command_failure_returns_a_distinguishable_read_failure(self):
        with patch(
            "lightcycle.adapters.github.subprocess.run",
            return_value=_proc("", returncode=1, stderr="gh: auth error"),
        ):
            result = self.adapter.last_push_time(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_non_pr_url_returns_read_failure(self):
        result = self.adapter.last_push_time("not-a-pr-url")

        self.assertIsInstance(result, ReadFailure)


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

    def test_non_pr_url_returns_a_distinguishable_read_failure(self):
        files = self.adapter.changed_files("not-a-pr-url", "abc123")

        self.assertIsInstance(files, ReadFailure)

    def test_unparseable_base_ref_returns_read_failure(self):
        pr_view = _proc("not json")
        mock_run = MagicMock(side_effect=[pr_view])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertIsInstance(files, ReadFailure)

    def test_empty_base_ref_returns_read_failure(self):
        pr_view = _proc(json.dumps({"baseRefName": ""}))
        mock_run = MagicMock(side_effect=[pr_view])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertIsInstance(files, ReadFailure)

    def test_unparseable_filenames_returns_read_failure(self):
        pr_view = _proc(json.dumps({"baseRefName": "main"}))
        compare = _proc("not json")
        mock_run = MagicMock(side_effect=[pr_view, compare])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            files = self.adapter.changed_files(_PR, "abc123")

        self.assertIsInstance(files, ReadFailure)


class TestCheckRuns(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _run(self, payload):
        return MagicMock(return_value=_proc(json.dumps(payload)))

    def test_parses_check_runs_into_tuples(self):
        mock_run = self._run([
            {"name": "build", "status": "completed", "conclusion": "success"},
            {"name": "test", "status": "completed", "conclusion": "failure"},
        ])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertEqual(
            runs,
            (
                CheckRun(name="build", status="completed", conclusion="success"),
                CheckRun(name="test", status="completed", conclusion="failure"),
            ),
        )

    def test_check_run_url_lands_on_the_check_run(self):
        mock_run = self._run([
            {"name": "test", "status": "completed", "conclusion": "failure",
             "url": "https://github.com/x/y/actions/runs/1/job/2"},
        ])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertEqual(runs[0].url, "https://github.com/x/y/actions/runs/1/job/2")

    def test_started_at_parses_to_epoch_and_missing_is_zero(self):
        mock_run = self._run([
            {"name": "a", "status": "completed", "conclusion": "success",
             "started_at": "2026-10-20T13:57:15Z"},
            {"name": "b", "status": "queued", "conclusion": None, "started_at": None},
        ])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertEqual(runs[0].started_at, 1792504635.0)
        self.assertEqual(runs[1].started_at, 0.0)

    def test_empty_check_runs_list(self):
        mock_run = self._run([])
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertEqual(runs, ())

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertEqual(runs, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            runs = self.adapter.check_runs(_PR, "sha1")

        self.assertIsInstance(runs, ReadFailure)

    def test_unparseable_pr_url_returns_read_failure(self):
        runs = self.adapter.check_runs("not-a-pr-url", "sha1")

        self.assertIsInstance(runs, ReadFailure)


def _timeout():
    return subprocess.TimeoutExpired(cmd=["gh"], timeout=30)


class TestReadFailureMethodsTimeOutCleanly(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_last_push_time_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.last_push_time(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_comments_since_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.comments_since(_PR, since=0.0)

        self.assertIsInstance(result, ReadFailure)

    def test_pull_comments_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.pull_comments(_PR, since=0.0)

        self.assertIsInstance(result, ReadFailure)

    def test_changed_files_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.changed_files(_PR, "abc123")

        self.assertIsInstance(result, ReadFailure)

    def test_check_runs_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.check_runs(_PR, "sha1")

        self.assertIsInstance(result, ReadFailure)


class TestReviewsTimeout(unittest.TestCase):
    def test_reviews_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = GitHubEventsAdapter().reviews(_PR, since=0.0)

        self.assertIsInstance(result, ReadFailure)


class TestIsMerged(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_is_merged_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.is_merged(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.is_merged(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.is_merged(_PR)

        self.assertIsInstance(result, ReadFailure)


class TestIsClosedUnmerged(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_is_closed_unmerged_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.is_closed_unmerged(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.is_closed_unmerged(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.is_closed_unmerged(_PR)

        self.assertIsInstance(result, ReadFailure)


class TestIsConflicted(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_is_conflicted_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.pr_sync_state(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.pr_sync_state(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.pr_sync_state(_PR)

        self.assertIsInstance(result, ReadFailure)


class TestHeadSha(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_head_sha_returns_read_failure_on_timeout(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.head_sha(_PR)

        self.assertIsInstance(result, ReadFailure)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="gh: auth error"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.head_sha(_PR)

        self.assertEqual(result, ReadFailure(1, "gh: auth error"))

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("not json", returncode=0))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.head_sha(_PR)

        self.assertIsInstance(result, ReadFailure)


class TestPrSyncState(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_behind_payload(self):
        payload = json.dumps(
            {"mergeStateStatus": "BEHIND", "headRefOid": "abc123", "baseRefName": "main"}
        )
        mock_run = MagicMock(return_value=_proc(payload))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.pr_sync_state(_PR)

        self.assertEqual(result, PrSync(True, False, "abc123", "x/y@main"))
        self.assertEqual(
            mock_run.call_args[0][0],
            ["gh", "pr", "view", _PR, "--json", "mergeable,mergeStateStatus,headRefOid,baseRefName"],
        )

    def test_unknown_is_not_behind(self):
        payload = json.dumps(
            {"mergeStateStatus": "UNKNOWN", "headRefOid": "abc123", "baseRefName": "main"}
        )
        with patch("lightcycle.adapters.github.subprocess.run",
                   MagicMock(return_value=_proc(payload))):
            result = self.adapter.pr_sync_state(_PR)

        self.assertFalse(result.behind)

    def test_failures(self):
        for run in (
            MagicMock(return_value=_proc("", returncode=1, stderr="auth")),
            MagicMock(return_value=_proc("not json")),
            MagicMock(side_effect=_timeout()),
        ):
            with patch("lightcycle.adapters.github.subprocess.run", run):
                self.assertIsInstance(self.adapter.pr_sync_state(_PR), ReadFailure)


class TestRequiresUpToDate(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _run(self, *procs):
        return patch("lightcycle.adapters.github.subprocess.run",
                     MagicMock(side_effect=list(procs)))

    def test_ruleset_strict(self):
        rules = json.dumps([
            {"type": "deletion"},
            {"type": "required_status_checks",
             "parameters": {"strict_required_status_checks_policy": True}},
        ])
        with self._run(_proc(rules)) as run:
            result = self.adapter.requires_up_to_date("x/y@main")

        self.assertIs(result, True)
        self.assertEqual(run.call_args[0][0],
                         ["gh", "api", "repos/x/y/rules/branches/main"])

    def test_ruleset_not_strict_and_protection_strict(self):
        rules = json.dumps([
            {"type": "required_status_checks",
             "parameters": {"strict_required_status_checks_policy": False}},
        ])
        with self._run(_proc(rules), _proc(json.dumps({"strict": True}))) as run:
            result = self.adapter.requires_up_to_date("x/y@main")

        self.assertIs(result, True)
        self.assertEqual(
            run.call_args[0][0],
            ["gh", "api", "repos/x/y/branches/main/protection/required_status_checks"],
        )

    def test_protection_not_strict(self):
        with self._run(_proc("[]"), _proc(json.dumps({"strict": False}))):
            self.assertIs(self.adapter.requires_up_to_date("x/y@main"), False)

    def test_not_protected_404_is_false(self):
        not_protected = _proc("", returncode=1, stderr="gh: Branch not protected (HTTP 404)")
        with self._run(_proc("[]"), not_protected):
            self.assertIs(self.adapter.requires_up_to_date("x/y@main"), False)

    def test_other_protection_error_is_read_failure(self):
        with self._run(_proc("[]"), _proc("", returncode=1, stderr="HTTP 403")):
            result = self.adapter.requires_up_to_date("x/y@main")

        self.assertIsInstance(result, ReadFailure)

    def test_rules_failures(self):
        for first in (
            _proc("", returncode=1, stderr="HTTP 500"),
            _proc("not json"),
        ):
            with self._run(first):
                self.assertIsInstance(
                    self.adapter.requires_up_to_date("x/y@main"), ReadFailure
                )

    def test_timeouts(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            self.assertIsInstance(
                self.adapter.requires_up_to_date("x/y@main"), ReadFailure
            )
        with self._run(_proc("[]"), _timeout()):
            self.assertIsInstance(
                self.adapter.requires_up_to_date("x/y@main"), ReadFailure
            )

    def test_bad_protection_json_is_read_failure(self):
        with self._run(_proc("[]"), _proc("not json")):
            self.assertIsInstance(
                self.adapter.requires_up_to_date("x/y@main"), ReadFailure
            )


class TestRequiredChecks(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _run(self, *procs):
        return patch("lightcycle.adapters.github.subprocess.run",
                     MagicMock(side_effect=list(procs)))

    def _ruleset(self, *contexts):
        return _proc(json.dumps([
            {"type": "deletion"},
            {"type": "required_status_checks",
             "parameters": {"required_status_checks": [{"context": c} for c in contexts]}},
        ]))

    def _not_protected(self):
        return _proc("", returncode=1, stderr="gh: Branch not protected (HTTP 404)")

    def test_ruleset_contexts(self):
        with self._run(self._ruleset("build", "test"), self._not_protected()):
            result = self.adapter.required_checks("x/y@main")

        self.assertEqual(result, frozenset({"build", "test"}))

    def test_protection_contexts_and_checks(self):
        payload = json.dumps({"contexts": ["build"], "checks": [{"context": "test", "app_id": 1}]})
        with self._run(_proc("[]"), _proc(payload)) as run:
            result = self.adapter.required_checks("x/y@main")

        self.assertEqual(result, frozenset({"build", "test"}))
        self.assertIn("timeout", run.call_args[1])

    def test_both_sources_union(self):
        with self._run(self._ruleset("build"), _proc(json.dumps({"contexts": ["test"]}))):
            result = self.adapter.required_checks("x/y@main")

        self.assertEqual(result, frozenset({"build", "test"}))

    def test_neither_gives_none(self):
        with self._run(_proc("[]"), self._not_protected()):
            self.assertIsNone(self.adapter.required_checks("x/y@main"))

    def test_empty_union_gives_none(self):
        with self._run(self._ruleset(), _proc(json.dumps({"contexts": [], "checks": []}))):
            self.assertIsNone(self.adapter.required_checks("x/y@main"))

    def test_ruleset_with_failing_protection_is_read_failure(self):
        with self._run(self._ruleset("build"), _proc("", returncode=1, stderr="HTTP 403")):
            self.assertIsInstance(self.adapter.required_checks("x/y@main"), ReadFailure)

    def test_rules_failures_and_timeouts(self):
        for first in (_proc("", returncode=1, stderr="HTTP 500"), _proc("not json")):
            with self._run(first):
                self.assertIsInstance(self.adapter.required_checks("x/y@main"), ReadFailure)
        with self._run(_proc("[]"), _timeout()):
            self.assertIsInstance(self.adapter.required_checks("x/y@main"), ReadFailure)
        with self._run(_proc("[]"), _proc("not json")):
            self.assertIsInstance(self.adapter.required_checks("x/y@main"), ReadFailure)


class TestRateLimit(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def _read(self, proc):
        with patch("lightcycle.adapters.github.subprocess.run", return_value=proc) as run:
            return self.adapter.rate_limit(), run

    def test_reads_the_core_bucket_through_one_gh_api_rate_limit_call(self):
        payload = json.dumps({"resources": {
            "core": {"limit": 5000, "remaining": 4261, "reset": 1792503970, "used": 739},
            "graphql": {"limit": 5000, "remaining": 1, "reset": 1},
        }})

        result, run = self._read(_proc(payload))

        self.assertEqual(result, RateLimit(limit=5000, remaining=4261, reset=1792503970))
        self.assertEqual(run.call_args.args[0], ["gh", "api", "rate_limit"])
        self.assertEqual(run.call_count, 1)

    def test_a_failed_gh_call_is_a_read_failure_not_zeros(self):
        result, _ = self._read(_proc(returncode=1, stderr="rate limit exceeded"))

        self.assertIsInstance(result, ReadFailure)
        self.assertEqual(result.returncode, 1)

    def test_a_missing_core_bucket_is_a_read_failure(self):
        result, _ = self._read(_proc(json.dumps({"resources": {}})))

        self.assertIsInstance(result, ReadFailure)

    def test_a_non_integer_field_is_a_read_failure(self):
        payload = json.dumps({"resources": {"core": {"limit": 5000, "remaining": "n/a", "reset": 1}}})

        result, _ = self._read(_proc(payload))

        self.assertIsInstance(result, ReadFailure)

    def test_a_missing_field_is_a_read_failure(self):
        payload = json.dumps({"resources": {"core": {"limit": 5000, "remaining": 10}}})

        result, _ = self._read(_proc(payload))

        self.assertIsInstance(result, ReadFailure)

    def test_unparseable_output_is_a_read_failure(self):
        result, _ = self._read(_proc("not json"))

        self.assertIsInstance(result, ReadFailure)


class TestUpdateBranch(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_argv_pins_expected_head_and_rebases(self):
        mock_run = MagicMock(return_value=_proc("{}"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.update_branch(_PR, "abc123")

        self.assertIsNone(result)
        self.assertEqual(
            mock_run.call_args[0][0],
            ["gh", "api", "-X", "PUT", "repos/x/y/pulls/7/update-branch",
             "-f", "expected_head_sha=abc123", "-f", "update_method=rebase"],
        )

    def test_refusal_is_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="HTTP 422"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            self.assertEqual(self.adapter.update_branch(_PR, "abc"), ReadFailure(1, "HTTP 422"))

    def test_timeout_is_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            self.assertIsInstance(self.adapter.update_branch(_PR, "abc"), ReadFailure)


if __name__ == "__main__":
    unittest.main()


_ISSUE = "https://github.com/x/y/issues/3"


class TestIssueState(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_closed_issue_returns_state_and_passes_a_timeout(self):
        mock_run = MagicMock(return_value=_proc(json.dumps({"state": "CLOSED"})))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.issue_state(_ISSUE)

        self.assertEqual(result, "CLOSED")
        self.assertEqual(
            mock_run.call_args.args[0], ["gh", "issue", "view", _ISSUE, "--json", "state"])
        self.assertIn("timeout", mock_run.call_args.kwargs)

    def test_non_zero_exit_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("", returncode=1, stderr="not found"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.issue_state(_ISSUE)

        self.assertEqual(result, ReadFailure(1, "not found"))

    def test_timeout_returns_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run", side_effect=_timeout()):
            result = self.adapter.issue_state(_ISSUE)

        self.assertIsInstance(result, ReadFailure)

    def test_invalid_json_returns_read_failure(self):
        mock_run = MagicMock(return_value=_proc("nope"))
        with patch("lightcycle.adapters.github.subprocess.run", mock_run):
            result = self.adapter.issue_state(_ISSUE)

        self.assertIsInstance(result, ReadFailure)


def _listing_page(rows):
    return _proc("\n".join(json.dumps(r) for r in rows))


def _row(n, updated, state="open", merged_at=None):
    return {
        "url": "https://github.com/x/y/pull/%d" % n, "updated_at": updated,
        "state": state, "merged_at": merged_at,
    }


class TestListPrs(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_returns_rows_at_or_after_the_cutoff_with_state_and_merge(self):
        page = [
            _row(3, "2026-01-03T00:00:00Z", "closed", "2026-01-03T00:00:00Z"),
            _row(2, "2026-01-02T00:00:00Z"),
            _row(1, "2026-01-01T00:00:00Z"),
        ]
        cutoff = 1767312000.0

        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_listing_page(page)) as run:
            listed = self.adapter.list_prs("x/y", cutoff)

        self.assertEqual([p.url[-1] for p in listed], ["3", "2"])
        self.assertTrue(listed[0].merged)
        self.assertEqual(listed[0].state, "closed")
        self.assertFalse(listed[1].merged)
        self.assertEqual(run.call_count, 1)
        argv = run.call_args.args[0]
        self.assertIn("repos/x/y/pulls?state=all&sort=updated&direction=desc&per_page=100&page=1",
                      argv)

    def test_pages_only_until_a_row_older_than_the_cutoff(self):
        full = [_row(n, "2026-02-01T00:00:00Z") for n in range(100)]
        tail = [_row(200, "2026-01-01T00:00:00Z")]

        with patch("lightcycle.adapters.github.subprocess.run",
                   side_effect=[_listing_page(full), _listing_page(tail)]) as run:
            listed = self.adapter.list_prs("x/y", 1769904000.0)

        self.assertEqual(len(listed), 100)
        self.assertEqual(run.call_count, 2)

    def test_stops_after_a_short_page_even_when_every_row_is_newer(self):
        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_listing_page([_row(1, "2026-02-01T00:00:00Z")])) as run:
            self.adapter.list_prs("x/y", 0.0)

        self.assertEqual(run.call_count, 1)

    def test_a_failing_call_is_a_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_proc(returncode=1, stderr="boom")):
            self.assertIsInstance(self.adapter.list_prs("x/y", 0.0), ReadFailure)


class TestRepoInlineComments(unittest.TestCase):
    def test_maps_api_urls_to_pr_urls(self):
        out = "\n".join(
            json.dumps(u) for u in [
                "https://api.github.com/repos/x/y/pulls/7",
                "https://api.github.com/repos/x/y/pulls/7",
                "https://api.github.com/repos/x/y/pulls/9",
            ])

        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_proc(out)) as run:
            urls = GitHubEventsAdapter().repo_inline_comments("x/y", 1767225600.0)

        self.assertEqual(urls, frozenset([
            "https://github.com/x/y/pull/7", "https://github.com/x/y/pull/9"]))
        self.assertIn(
            "repos/x/y/pulls/comments?since=2026-01-01T00:00:00Z&sort=updated"
            "&direction=desc&per_page=100", run.call_args.args[0])


class TestBranchTipAndPrView(unittest.TestCase):
    def setUp(self):
        self.adapter = GitHubEventsAdapter()

    def test_authenticated_login_with_empty_stdout_is_a_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run", return_value=_proc("")):
            self.assertIsInstance(self.adapter.authenticated_login(), ReadFailure)

    def test_authenticated_login_returns_the_login(self):
        with patch("lightcycle.adapters.github.subprocess.run", return_value=_proc("octocat\n")):
            self.assertEqual(self.adapter.authenticated_login(), "octocat")

    def test_branch_tip_returns_the_sha(self):
        with patch("lightcycle.adapters.github.subprocess.run", return_value=_proc("abc123\n")):
            self.assertEqual(self.adapter.branch_tip("x/y", "main"), "abc123")

    def test_branch_tip_failure_is_a_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_proc(returncode=1, stderr="404")):
            self.assertIsInstance(self.adapter.branch_tip("x/y", "main"), ReadFailure)

    def test_pr_view_parses_every_field_of_the_shared_view(self):
        payload = json.dumps({
            "state": "OPEN", "headRefOid": "h1", "baseRefName": "main",
            "mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY",
            "updatedAt": "2026-01-01T00:00:00Z",
        })

        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_proc(payload)) as run:
            view = self.adapter.pr_view(_PR)

        self.assertEqual(view.state, "OPEN")
        self.assertEqual(view.head_sha, "h1")
        self.assertEqual(view.base_ref, "main")
        self.assertEqual(view.base_key, "x/y@main")
        self.assertEqual(view.mergeable, "CONFLICTING")
        self.assertEqual(view.merge_state_status, "DIRTY")
        self.assertEqual(view.updated_at, 1767225600.0)
        self.assertEqual(run.call_count, 1)
        self.assertIn(
            "state,headRefOid,baseRefName,mergeable,mergeStateStatus,updatedAt",
            run.call_args.args[0])

    def test_pr_view_with_bad_json_is_a_read_failure(self):
        with patch("lightcycle.adapters.github.subprocess.run", return_value=_proc("{}")):
            self.assertIsInstance(self.adapter.pr_view(_PR), ReadFailure)

    def test_changed_files_with_a_base_makes_only_the_compare_call(self):
        with patch("lightcycle.adapters.github.subprocess.run",
                   return_value=_proc('["a.py"]')) as run:
            files = self.adapter.changed_files(_PR, "sha1", "main")

        self.assertEqual(files, frozenset(["a.py"]))
        self.assertEqual(run.call_count, 1)
        self.assertIn("/repos/x/y/compare/main...sha1", run.call_args.args[0])
