import unittest

from lightcycle.application.pool.tick import TickResponse
from lightcycle.cli import _format_tick

_NOW = 1751500862.0  # 2025-07-03 fixed timestamp for stable output


def _result(**kw):
    defaults = dict(swept=[], pruned=0, spawned=[], merged=[], abandoned=[], reworked=[],
                    hook_completed=[], cadence_fired=[], alive=0, max_agents=4, ready=0,
                    inflight_count=0)
    defaults.update(kw)
    return TickResponse(**defaults)


class TestFormatTick(unittest.TestCase):

    def test_spawn_rendered_per_role(self):
        result = _result(spawned=["coder", "reviewer"], alive=2, ready=0)
        lines, _ = _format_tick(result, None, _NOW)
        spawn_lines = [l for l in lines if "spawn" in l]
        self.assertEqual(len(spawn_lines), 2)
        self.assertIn("coder", spawn_lines[0])
        self.assertIn("reviewer", spawn_lines[1])

    def test_spawn_line_format(self):
        result = _result(spawned=["coder"])
        lines, _ = _format_tick(result, None, _NOW)
        spawn_line = lines[0]
        self.assertRegex(spawn_line, r'^\d{2}:\d{2}:\d{2}\s+spawn\s+coder$')

    def test_state_emitted_when_no_prev(self):
        result = _result(alive=1, max_agents=4, ready=2, inflight_count=1)
        lines, _ = _format_tick(result, None, _NOW)
        state_lines = [l for l in lines if "state" in l]
        self.assertEqual(len(state_lines), 1)
        self.assertIn("active=1/4", state_lines[0])
        self.assertIn("ready=2", state_lines[0])
        self.assertIn("inflight=1", state_lines[0])

    def test_state_suppressed_when_snapshot_unchanged_no_prune(self):
        result = _result(alive=1, max_agents=4, ready=2, inflight_count=0)
        prev = (1, 4, 2, 0)
        lines, _ = _format_tick(result, prev, _NOW)
        state_lines = [l for l in lines if "state" in l]
        self.assertEqual(len(state_lines), 0)

    def test_state_shown_when_alive_changes(self):
        result = _result(alive=2, max_agents=4, ready=1, inflight_count=0)
        prev = (1, 4, 1, 0)
        lines, _ = _format_tick(result, prev, _NOW)
        state_lines = [l for l in lines if "state" in l]
        self.assertEqual(len(state_lines), 1)
        self.assertIn("active=2/4", state_lines[0])

    def test_state_shown_when_ready_changes(self):
        result = _result(alive=1, max_agents=4, ready=3, inflight_count=0)
        prev = (1, 4, 2, 0)
        lines, _ = _format_tick(result, prev, _NOW)
        state_lines = [l for l in lines if "state" in l]
        self.assertEqual(len(state_lines), 1)

    def test_prune_shown_in_state_even_when_snapshot_unchanged(self):
        result = _result(pruned=2, alive=1, max_agents=4, ready=0, inflight_count=0)
        prev = (1, 4, 0, 0)
        lines, _ = _format_tick(result, prev, _NOW)
        state_lines = [l for l in lines if "state" in l]
        self.assertEqual(len(state_lines), 1)
        self.assertIn("pruned=2", state_lines[0])

    def test_snapshot_returned_reflects_current_state(self):
        result = _result(alive=2, max_agents=4, ready=3, inflight_count=1)
        _, snapshot = _format_tick(result, None, _NOW)
        self.assertEqual(snapshot, (2, 4, 3, 1))

    def test_merge_and_sweep_lines_rendered(self):
        result = _result(merged=["abc.1"], swept=["xyz.2"])
        lines, _ = _format_tick(result, None, _NOW)
        self.assertTrue(any("merge" in l and "abc.1" in l for l in lines))
        self.assertTrue(any("sweep" in l and "xyz.2" in l for l in lines))

    def test_event_order_spawn_before_merge_before_sweep(self):
        result = _result(spawned=["coder"], merged=["m.1"], swept=["s.1"],
                         alive=1, max_agents=4)
        lines, _ = _format_tick(result, None, _NOW)
        event_lines = [l for l in lines if "state" not in l]
        events = [l.split("  ")[1].strip() for l in event_lines]
        self.assertEqual(events.index("spawn"), 0)
        self.assertLess(events.index("merge"), events.index("sweep"))

    def test_hook_completion_rendered_with_step_and_detail(self):
        result = _result(spawned=["auditor"], hook_completed=[("audit", "audit.3", "no finding")])
        lines, _ = _format_tick(result, None, _NOW)
        spawn_lines = [l for l in lines if "spawn" in l]
        self.assertEqual(len(spawn_lines), 1)
        self.assertIn("auditor", spawn_lines[0])
        audit_lines = [l for l in lines if "audit.3" in l]
        self.assertEqual(len(audit_lines), 1)
        self.assertRegex(audit_lines[0], r'^\d{2}:\d{2}:\d{2}\s+audit\s+audit\.3: no finding$')

    def test_hook_completion_filed_finding_rendered(self):
        result = _result(hook_completed=[("audit", "audit.4", "filed: fix flaky retry")])
        lines, _ = _format_tick(result, None, _NOW)
        self.assertTrue(any("filed:" in l and "audit.4" in l for l in lines))

    def test_hook_completion_without_detail_renders_id_only(self):
        result = _result(hook_completed=[("audit", "audit.5", "")])
        lines, _ = _format_tick(result, None, _NOW)
        self.assertTrue(any(l.endswith("audit.5") for l in lines))

    def test_multiple_hook_completions_each_rendered(self):
        result = _result(hook_completed=[
            ("audit", "audit.1", "no finding"),
            ("audit", "audit.2", "filed: x"),
        ])
        lines, _ = _format_tick(result, None, _NOW)
        self.assertTrue(any("audit.1" in l for l in lines))
        self.assertTrue(any("audit.2" in l for l in lines))

    def test_no_hook_completions_renders_no_extra_lines(self):
        result = _result()
        lines, _ = _format_tick(result, None, _NOW)
        self.assertEqual([l for l in lines if "state" not in l], [])

    def test_cadence_fired_rendered_as_audit_line(self):
        result = _result(cadence_fired=["audit.7"])
        lines, _ = _format_tick(result, None, _NOW)
        audit_lines = [l for l in lines if "audit.7" in l]
        self.assertEqual(len(audit_lines), 1)
        self.assertRegex(audit_lines[0], r'^\d{2}:\d{2}:\d{2}\s+audit\s+audit\.7$')

    def test_cadence_fired_empty_renders_no_audit_line(self):
        result = _result(cadence_fired=[])
        lines, _ = _format_tick(result, None, _NOW)
        self.assertEqual([l for l in lines if "audit" in l], [])


if __name__ == "__main__":
    unittest.main()
