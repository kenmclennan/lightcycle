import unittest

from lightcycle.application.pool.pr_writes import RULE_TTL_SECONDS, PrWrites
from lightcycle.ports.github import ReadFailure
from tests.support.fake_github import FakeGitHub

_BASE = "acme/widget@main"


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TestRequiredChecksCache(unittest.TestCase):
    def test_value_is_cached_for_the_ttl(self):
        clock = _Clock()
        github = FakeGitHub(required_by_base={_BASE: ["build"]})
        writes = PrWrites(clock)

        first = writes.required_checks(github, _BASE)
        clock.now = RULE_TTL_SECONDS - 1
        writes.required_checks(github, _BASE)
        clock.now = RULE_TTL_SECONDS + 1
        writes.required_checks(github, _BASE)

        self.assertEqual(first, frozenset({"build"}))
        self.assertEqual(github.calls.count(("required_checks", _BASE)), 2)

    def test_none_is_cached(self):
        github = FakeGitHub()
        writes = PrWrites(_Clock())

        writes.required_checks(github, _BASE)
        writes.required_checks(github, _BASE)

        self.assertEqual(github.calls.count(("required_checks", _BASE)), 1)

    def test_read_failure_is_not_cached(self):
        github = FakeGitHub(failing_calls={"required_checks"})
        writes = PrWrites(_Clock())

        first = writes.required_checks(github, _BASE)
        writes.required_checks(github, _BASE)

        self.assertIsInstance(first, ReadFailure)
        self.assertEqual(github.calls.count(("required_checks", _BASE)), 2)
