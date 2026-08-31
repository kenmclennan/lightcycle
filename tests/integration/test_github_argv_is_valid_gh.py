import subprocess
import unittest
from unittest.mock import patch

from lightcycle.adapters.github import GitHubEventsAdapter

_PR = "https://github.com/acme/widget/pull/1"

_FLAG_ERRORS = ("unknown shorthand flag", "unknown flag", "unknown command")


def _captured_argvs():
    adapter = GitHubEventsAdapter()
    calls = []

    def _record(argv, *a, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with patch("lightcycle.adapters.github.subprocess.run", side_effect=_record):
        adapter.is_merged(_PR)
        adapter.is_closed_unmerged(_PR)
        adapter.last_push_time(_PR)
        adapter.is_conflicted(_PR)
        adapter.comments_since(_PR, 0.0)
        adapter.pull_comments(_PR, 0.0)
        adapter.reviews(_PR, 0.0)
        adapter.head_sha(_PR)
        adapter.changed_files(_PR, "deadbeef")

    return [c for c in calls if c and c[0] == "gh"]


class TestEveryGhArgvParses(unittest.TestCase):
    def test_gh_accepts_every_flag_the_adapter_passes(self):
        argvs = _captured_argvs()
        self.assertTrue(argvs)

        rejected = []
        for argv in argvs:
            result = subprocess.run(argv, capture_output=True, text=True)
            stderr = result.stderr.lower()
            if any(err in stderr for err in _FLAG_ERRORS):
                rejected.append((argv, result.stderr.splitlines()[0]))

        self.assertEqual(rejected, [])


if __name__ == "__main__":
    unittest.main()
