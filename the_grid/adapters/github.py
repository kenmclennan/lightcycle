"""GitHub Events Adapter: checks PR state via the gh CLI."""
import json
import subprocess

from the_grid.ports.github import GitHubEventsPort


class GitHubEventsAdapter(GitHubEventsPort):

    def _pr_state(self, pr: str) -> str:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "state"],
            capture_output=True, text=True)
        if result.returncode != 0:
            return ""
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return ""
        return data.get("state", "")

    def is_merged(self, pr: str) -> bool:
        return self._pr_state(pr) == "MERGED"

    def is_closed_unmerged(self, pr: str) -> bool:
        return self._pr_state(pr) == "CLOSED"
