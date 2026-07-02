"""GitHub Events Adapter: checks PR state via the gh CLI."""
import json
import subprocess

from the_grid.ports.github import GitHubEventsPort


class GitHubEventsAdapter(GitHubEventsPort):

    def is_merged(self, pr: str) -> bool:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "state"],
            capture_output=True, text=True)
        if result.returncode != 0:
            return False
        try:
            data = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return False
        return data.get("state") == "MERGED"
