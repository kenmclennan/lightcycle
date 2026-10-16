import unittest

from lightcycle.application.flow import CompleteStepUseCase
from lightcycle.application.pool import MonitorPrsUseCase
from lightcycle.application.work.behind_reason import behind_reason
from lightcycle.application.pool.update_behind_prs import (
    RULE_TTL_SECONDS,
    UPDATE_CAP,
    UpdateBehindPrsUseCase,
)
from tests.support.fake_fs import flow_from_metas
from tests.support.fake_github import FakeGitHub
from tests.support.fake_store import FakeStore
from tests.unit.test_dispatch_pr_feedback import _FlowAdapter, plant_pr
from tests.unit.test_monitor_prs import FakeWorktrees

_FLOW = flow_from_metas(
    {
        "watcher": {
            "model": "sonnet",
            "step": "watch-step",
            "routes": {
                "merged": "done-step",
                "abandoned": "done-step",
                "conflicted": "fix-step",
                "gave-up": "escalate-step",
            },
            "on_pr_merge": "merged",
            "on_pr_close": "abandoned",
            "on_pr_conflict": "conflicted",
            "on_pr_conflict_cap": 2,
            "on_pr_conflict_escalate": "gave-up",
        },
        "fixer": {"model": "sonnet", "step": "fix-step", "routes": {"resolved": "watch-step"}},
    }
)

_BASE = "acme/widget@main"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _pr(n):
    return "https://github.com/x/y/pull/%d" % n


class _Harness:
    def __init__(self, github):
        self.store = FakeStore()
        self.github = github
        self.clock = _Clock()
        self.uc = UpdateBehindPrsUseCase(
            self.store, github, _FlowAdapter(_FLOW), self.clock
        )

    def gate(self, url, title="feature"):
        item = self.store.create_item(title, "d")
        plant_pr(self.store, item, url)
        step = self.store.create_step(step="watch-step", role="human", parent=item)
        return item, step

    def notes(self, step):
        return self.store.get_node(step).notes or ""


def _behind(n, head="sha1", strict=True, **kw):
    url = _pr(n)
    return FakeGitHub(
        behind_prs={url}, head_shas={url: head},
        strict_bases={_BASE} if strict else (), **kw,
    ), url


class TestUpdatePath(unittest.TestCase):
    def test_behind_strict_gate_is_updated_with_expected_sha_and_stays_open(self):
        github, url = _behind(1, head="abcdef1234")
        h = _Harness(github)
        item, step = h.gate(url)

        result = h.uc.execute()

        self.assertEqual(github.update_calls, [(url, "abcdef1234")])
        self.assertEqual(result.updated, [item])
        self.assertEqual(result.update_failed, [])
        self.assertNotEqual(h.store.get_node(step).state, "done")
        self.assertIn("Branch updated onto main", h.notes(step))
        self.assertIn("abcdef1", h.notes(step))

    def test_non_strict_base_is_left_alone(self):
        github, url = _behind(2, strict=False)
        h = _Harness(github)
        item, step = h.gate(url)

        result = h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual((result.updated, result.update_failed), ([], []))
        self.assertEqual(h.notes(step), "")

    def test_not_behind_is_left_alone(self):
        url = _pr(3)
        github = FakeGitHub(head_shas={url: "s"}, strict_bases={_BASE})
        h = _Harness(github)
        h.gate(url)

        result = h.uc.execute()

        self.assertEqual(github.update_calls, [])
        self.assertEqual(github.requires_calls, [])
        self.assertEqual(result.updated, [])

    def test_step_without_merge_hook_is_ignored(self):
        github, url = _behind(4)
        h = _Harness(github)
        item = h.store.create_item("f", "d")
        plant_pr(h.store, item, url)
        h.store.create_step(step="fix-step", role="agent", parent=item)

        h.uc.execute()

        self.assertEqual(github.update_calls, [])


class TestRuleCache(unittest.TestCase):
    def test_rule_read_once_inside_ttl_and_again_after(self):
        url = _pr(5)
        github = FakeGitHub(behind_prs={url}, head_shas={url: "s"})
        h = _Harness(github)
        h.gate(url)

        h.uc.execute()
        h.uc.execute()
        self.assertEqual(github.requires_calls, [_BASE])

        h.clock.now += RULE_TTL_SECONDS + 1
        h.uc.execute()
        self.assertEqual(github.requires_calls, [_BASE, _BASE])

    def test_rule_read_failure_is_cached_and_noted(self):
        url = _pr(6)
        github = FakeGitHub(
            behind_prs={url}, head_shas={url: "s"}, failing_calls={"requires_up_to_date"}
        )
        h = _Harness(github)
        item, step = h.gate(url)

        h.uc.execute()
        h.uc.execute()

        self.assertEqual(github.requires_calls, [_BASE])
        self.assertIn("up-to-date rule", h.notes(step))
        self.assertEqual(github.update_calls, [])


class TestFailureBounds(unittest.TestCase):
    def test_failed_update_is_reported_and_not_retried_until_head_changes(self):
        github, url = _behind(7, head="h1", failing_calls={"update_branch"})
        h = _Harness(github)
        item, step = h.gate(url)

        first = h.uc.execute()
        h.uc.execute()

        self.assertEqual(first.update_failed, [item])
        self.assertEqual(first.updated, [])
        self.assertEqual(len(github.update_calls), 1)
        self.assertIn("update-branch refused", h.notes(step))

        github._head_shas[url] = "h2"
        h.uc.execute()
        self.assertEqual(len(github.update_calls), 2)

    def test_head_moved_between_read_and_update_fails_closed(self):
        github, url = _behind(8, head="h1")
        real = github.pr_sync_state

        def stale_read(pr):
            sync = real(pr)
            github._head_shas[pr] = "h-pushed"
            return sync

        github.pr_sync_state = stale_read
        h = _Harness(github)
        item, step = h.gate(url)

        result = h.uc.execute()

        self.assertEqual(result.update_failed, [item])
        self.assertEqual(github.update_calls, [(url, "h1")])
        self.assertIn("update-branch refused", h.notes(step))

    def test_cap_stops_updates_and_notes_once(self):
        github, url = _behind(9, head="h0")
        h = _Harness(github)
        item, step = h.gate(url)

        for n in range(UPDATE_CAP):
            self.assertEqual(h.uc.execute().updated, [item])
            github._behind.add(url)
        calls = len(github.update_calls)
        h.uc.execute()
        h.uc.execute()

        self.assertEqual(len(github.update_calls), calls)
        self.assertEqual(h.notes(step).count("update cap reached"), 1)

    def test_sync_read_failure_is_noted_and_does_not_abort_the_pass(self):
        github, url = _behind(10, head="h1")
        other = _pr(11)
        github._behind.add(other)
        github._head_shas[other] = "o1"
        real = github.pr_sync_state

        def flaky(pr):
            if pr == other:
                from lightcycle.ports.github import ReadFailure
                return ReadFailure(1, "gh: boom")
            return real(pr)

        github.pr_sync_state = flaky
        h = _Harness(github)
        bad_item, bad_step = h.gate(other, "bad")
        good_item, good_step = h.gate(url, "good")

        result = h.uc.execute()

        self.assertEqual(result.updated, [good_item])
        self.assertIn("gh: boom", h.notes(bad_step))


class TestPerGateCount(unittest.TestCase):
    def _next_gate(self, h, item, old):
        h.store.complete_node(old, "merged")
        return h.store.create_step(step="watch-step", role="human", parent=item)

    def test_pr_replaced_gate_by_gate_is_never_capped(self):
        github, url = _behind(50, head="h0")
        h = _Harness(github)
        item, step = h.gate(url)
        steps = [step]

        for n in range(UPDATE_CAP + 2):
            self.assertEqual(h.uc.execute().updated, [item])
            github._behind.add(url)
            github._head_shas[url] = "h%d" % (n + 1)
            steps.append(self._next_gate(h, item, steps[-1]))

        self.assertEqual(len(github.update_calls), UPDATE_CAP + 2)
        for sid in steps:
            self.assertNotIn("update cap reached", h.notes(sid))

    def test_cap_note_lands_on_each_capped_gate(self):
        github, url = _behind(51, head="h0")
        h = _Harness(github)
        item, a = h.gate(url)

        def cap(step):
            for _ in range(UPDATE_CAP):
                self.assertEqual(h.uc.execute().updated, [item])
                github._behind.add(url)
                github._head_shas[url] += "x"
            h.uc.execute()
            h.uc.execute()

        cap(a)
        b = self._next_gate(h, item, a)
        cap(b)

        self.assertEqual(h.notes(a).count("update cap reached"), 1)
        self.assertEqual(h.notes(b).count("update cap reached"), 1)


class TestBehindMarker(unittest.TestCase):
    def _capped(self):
        github, url = _behind(60, head="h0")
        h = _Harness(github)
        item, step = h.gate(url)
        for _ in range(UPDATE_CAP):
            h.uc.execute()
            github._behind.add(url)
            github._head_shas[url] += "x"
        h.uc.execute()
        return github, url, h, step

    def test_cap_sets_marker_and_not_behind_clears_it(self):
        github, url, h, step = self._capped()

        self.assertIn("update cap reached", behind_reason(h.store, step))

        github._behind.discard(url)
        h.uc.execute()

        self.assertIsNone(behind_reason(h.store, step))

    def test_marker_write_is_change_only(self):
        github, url, h, step = self._capped()
        real = h.store.replace_artifact
        calls = []
        h.store.replace_artifact = lambda *a, **k: (calls.append(a), real(*a, **k))[1]

        h.uc.execute()
        h.uc.execute()

        self.assertEqual(calls, [])

    def test_refused_update_sets_marker_and_success_clears_it(self):
        github, url = _behind(61, head="h1", failing_calls={"update_branch"})
        h = _Harness(github)
        item, step = h.gate(url)

        h.uc.execute()
        self.assertEqual(behind_reason(h.store, step), "update-branch refused")

        github._failing_calls.discard("update_branch")
        github._head_shas[url] = "h2"
        h.uc.execute()

        self.assertIsNone(behind_reason(h.store, step))

    def test_sync_read_failure_leaves_marker(self):
        github, url, h, step = self._capped()
        from lightcycle.ports.github import ReadFailure
        github.pr_sync_state = lambda pr: ReadFailure(1, "gh: boom")

        h.uc.execute()

        self.assertIn("update cap reached", behind_reason(h.store, step))

    def test_base_not_requiring_up_to_date_clears_marker(self):
        github, url = _behind(62, head="h1", failing_calls={"update_branch"})
        h = _Harness(github)
        item, step = h.gate(url)
        h.uc.execute()
        self.assertIsNotNone(behind_reason(h.store, step))

        github._strict_bases.clear()
        github._head_shas[url] = "h2"
        h.clock.now += RULE_TTL_SECONDS + 1
        h.uc.execute()

        self.assertIsNone(behind_reason(h.store, step))


class TestBehindReason(unittest.TestCase):
    def test_none_blank_and_latest_wins(self):
        store = FakeStore()
        item = store.create_item("f", "d")
        step = store.create_step(step="watch-step", role="human", parent=item)
        self.assertIsNone(behind_reason(store, step))

        store.add_artifact(step, "behind-not-updated", "first", internal=True)
        store.add_artifact(step, "behind-not-updated", "second", internal=True)
        self.assertEqual(behind_reason(store, step), "second")

        store.add_artifact(step, "behind-not-updated", "", internal=True)
        self.assertIsNone(behind_reason(store, step))


class TestMixedGates(unittest.TestCase):
    def test_only_behind_strict_gate_is_updated(self):
        a, b, c = _pr(20), _pr(21), _pr(22)
        github = FakeGitHub(
            behind_prs={a, b}, head_shas={a: "a1", b: "b1", c: "c1"},
            strict_bases={_BASE}, base_keys={b: "acme/widget@other"},
        )
        h = _Harness(github)
        ia, sa = h.gate(a, "a")
        ib, sb = h.gate(b, "b")
        ic, sc = h.gate(c, "c")

        result = h.uc.execute()

        self.assertEqual(result.updated, [ia])
        self.assertEqual(github.update_calls, [(a, "a1")])
        self.assertEqual(h.notes(sb), "")
        self.assertEqual(h.notes(sc), "")


class TestConflictFallThrough(unittest.TestCase):
    def test_failed_update_then_conflict_routes_through_existing_path(self):
        github, url = _behind(30, head="h1", failing_calls={"update_branch"})
        store = FakeStore()
        item = store.create_item("f", "d")
        plant_pr(store, item, url)
        step = store.create_step(step="watch-step", role="agent", parent=item)
        flow = _FlowAdapter(_FLOW)
        monitor = MonitorPrsUseCase(
            store, github, FakeWorktrees(), flow, CompleteStepUseCase(store, flow),
            trusted_authors=lambda: frozenset({"reviewer"}), held_shortcode=lambda: "HLD",
        )

        first = monitor.execute()
        self.assertEqual(first.update_failed, [item])
        self.assertNotEqual(store.get_node(step).state, "done")

        github._conflicted.add(url)
        second = monitor.execute()

        self.assertEqual(second.conflicted, [item])
        self.assertEqual(store.get_node(step).outcome, "conflicted")


class TestOneReadPerPrPerTick(unittest.TestCase):
    def _monitor(self, github, url):
        store = FakeStore()
        item = store.create_item("f", "d")
        plant_pr(store, item, url)
        store.create_step(step="watch-step", role="agent", parent=item)
        flow = _FlowAdapter(_FLOW)
        return MonitorPrsUseCase(
            store, github, FakeWorktrees(), flow, CompleteStepUseCase(store, flow),
            trusted_authors=lambda: frozenset({"reviewer"}), held_shortcode=lambda: "HLD",
        )

    def test_behind_pr_is_read_once_per_tick(self):
        github, url = _behind(40, head="h1")
        monitor = self._monitor(github, url)

        monitor.execute()

        self.assertEqual(github.sync_calls, [url])

    def test_conflicted_pr_is_read_once_per_tick(self):
        url = _pr(41)
        github = FakeGitHub(conflicted_prs={url}, head_shas={url: "h1"})
        monitor = self._monitor(github, url)

        result = monitor.execute()

        self.assertEqual(github.sync_calls, [url])
        self.assertEqual(len(result.conflicted), 1)

    def test_each_tick_reads_afresh(self):
        github, url = _behind(42, head="h1", strict=False)
        monitor = self._monitor(github, url)

        monitor.execute()
        monitor.execute()

        self.assertEqual(github.sync_calls, [url, url])


if __name__ == "__main__":
    unittest.main()
