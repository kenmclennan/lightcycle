import unittest
from types import SimpleNamespace

from lightcycle.application.pool.reap_orphan_processes import OrphanProcess
from lightcycle.application.pool.sweep import SweepResponse
from lightcycle.cli import _tick_event_lines


class TestTickEventLinesOrphans(unittest.TestCase):
    def test_orphan_kill_fail_and_left_lines_are_rendered(self):
        monitor = SimpleNamespace(
            merged=[], abandoned=[], reworked=[], conflicted=[], head_moved=[],
            shape_changed=[], ci_resolved=[], ci_unread=[])
        sweep = SweepResponse(
            swept=[], killed=[], pruned=0,
            orphans_ended=[OrphanProcess(11, "/w/a")],
            orphans_unended=[OrphanProcess(12, "/w/b")],
            orphans_left=[OrphanProcess(13, "/w/c")])
        result = SimpleNamespace(
            spawned=[], monitor=monitor, sweep=sweep, stranded=None, config=None,
            schedules=None, hooks=SimpleNamespace(completed=[]),
            backup=SimpleNamespace(created=None),
            breaker=SimpleNamespace(opened=False, closed=False, rearmed=False, spin_opened=False),
            github=None)

        lines = _tick_event_lines(result, "T")

        self.assertIn("T  orphan-kill  11 /w/a", lines)
        self.assertIn("T  orphan-fail  12 /w/b", lines)
        self.assertIn("T  orphan-left  13 /w/c", lines)
