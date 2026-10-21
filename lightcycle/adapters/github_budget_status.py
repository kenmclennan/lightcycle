import json
import os
import sys

from lightcycle.domain.pool import github_budget_from_state
from lightcycle.ports.github_budget_status import GithubBudgetStatusPort


def github_budget_status_path(root):
    return os.path.join(root, "logs", "github_budget.json")


def load(root):
    p = github_budget_status_path(root)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return github_budget_from_state(json.loads(f.read()))
    except Exception as e:
        sys.stderr.write("warning: could not read github budget state %s: %s\n" % (p, e))
        return None


def save(root, state):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    p = github_budget_status_path(root)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w") as f:
        f.write(json.dumps(state.as_dict(), indent=2))
    os.replace(tmp, p)


class GithubBudgetStatusAdapter(GithubBudgetStatusPort):
    def __init__(self, config):
        self._config = config

    def load(self):
        return load(self._config.data_root())

    def save(self, state):
        return save(self._config.data_root(), state)
