import json
import os
import subprocess
import unittest
from unittest.mock import MagicMock, mock_open, patch

from lightcycle.adapters.machine import (
    MachineAdapter, _headroom_linux, _headroom_macos,
    _linux_pid_footprint_kb, _linux_pool_footprint_kb, _macos_footprint_kb,
    _macos_pool_footprint_kb, _smaps_rollup_pss_kb,
    _status_vm_hwm_kb, _worker_pids,
)
from lightcycle.domain.pool.worker import Worker
from tests.support.fake_machine import FakeMachine


def _proc(stdout=b"", returncode=0):
    return MagicMock(returncode=returncode, stdout=stdout)


class TestMachineAdapterSelfRss(unittest.TestCase):
    def setUp(self):
        self.adapter = MachineAdapter()

    def test_returns_the_parsed_integer_when_ps_succeeds(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(b"123456\n")
        ):
            self.assertEqual(self.adapter.self_rss(), 123456)

    def test_returns_none_when_the_subprocess_call_fails(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            side_effect=OSError("no such command"),
        ):
            self.assertIsNone(self.adapter.self_rss())

    def test_returns_none_when_the_subprocess_call_times_out(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ps", timeout=2),
        ):
            self.assertIsNone(self.adapter.self_rss())

    def test_returns_none_when_ps_exits_non_zero(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            return_value=_proc(b"", returncode=1),
        ):
            self.assertIsNone(self.adapter.self_rss())

    def test_returns_none_when_the_output_does_not_parse_as_an_integer(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(b"not-a-number\n")
        ):
            self.assertIsNone(self.adapter.self_rss())

    def test_invokes_ps_with_its_own_pid(self):
        mock_run = MagicMock(return_value=_proc(b"1\n"))
        with patch("lightcycle.adapters.machine.subprocess.run", mock_run):
            self.adapter.self_rss()

        argv = mock_run.call_args.args[0]
        self.assertIn(str(os.getpid()), argv)
        self.assertEqual(argv[argv.index("-p") + 1], str(os.getpid()))


class TestHeadroomMacos(unittest.TestCase):
    def test_pool_share_and_peak_worker_share_populated_from_footprint(self):
        with patch("lightcycle.adapters.machine._macos_total_memory_kb", return_value=1000.0), \
             patch(
                 "lightcycle.adapters.machine._macos_pool_footprint_kb",
                 return_value=(100.0, 250.0),
             ):
            headroom = _headroom_macos([])

        self.assertEqual(headroom.pool_share, 0.1)
        self.assertEqual(headroom.peak_worker_share, 0.25)

    def test_pool_share_is_none_when_total_memory_read_fails(self):
        with patch("lightcycle.adapters.machine._macos_total_memory_kb", return_value=None):
            headroom = _headroom_macos([])

        self.assertIsNone(headroom.pool_share)
        self.assertIsNone(headroom.peak_worker_share)


class TestHeadroomLinux(unittest.TestCase):
    def test_pool_share_and_peak_worker_share_populated_from_footprint(self):
        with patch(
                 "lightcycle.adapters.machine._proc_meminfo",
                 return_value={"MemTotal": 1000.0},
             ), \
             patch(
                 "lightcycle.adapters.machine._linux_pool_footprint_kb",
                 return_value=(100.0, 250.0),
             ):
            headroom = _headroom_linux([])

        self.assertEqual(headroom.pool_share, 0.1)
        self.assertEqual(headroom.peak_worker_share, 0.25)

    def test_pool_share_is_none_when_meminfo_read_fails(self):
        with patch("lightcycle.adapters.machine._proc_meminfo", return_value=None):
            headroom = _headroom_linux([])

        self.assertIsNone(headroom.pool_share)
        self.assertIsNone(headroom.peak_worker_share)


class TestMacosFootprintKb(unittest.TestCase):
    def test_returns_empty_dict_without_a_subprocess_call_when_no_pids(self):
        with patch("lightcycle.adapters.machine._run") as mock_run:
            self.assertEqual(_macos_footprint_kb([]), {})
        mock_run.assert_not_called()

    def test_parses_a_real_shaped_json_payload_into_current_and_peak_kb(self):
        payload = {
            "processes": [
                {
                    "pid": 111,
                    "auxiliary": {"phys_footprint": 241172480, "phys_footprint_peak": 1249902592},
                },
            ]
        }

        def _write_payload(argv):
            with open(argv[3], "w") as f:
                json.dump(payload, f)
            return ""

        with patch("lightcycle.adapters.machine._run", side_effect=_write_payload):
            result = _macos_footprint_kb([111])

        self.assertEqual(result, {111: (235520.0, 1220608.0)})

    def test_excludes_a_process_entry_missing_footprint_fields(self):
        payload = {"processes": [{"pid": 111, "auxiliary": {"phys_footprint": 1024}}]}

        def _write_payload(argv):
            with open(argv[3], "w") as f:
                json.dump(payload, f)
            return ""

        with patch("lightcycle.adapters.machine._run", side_effect=_write_payload):
            result = _macos_footprint_kb([111])

        self.assertEqual(result, {})

    def test_skips_a_reaped_process_whose_auxiliary_block_is_null(self):
        payload = {
            "processes": [
                {"pid": 111, "auxiliary": None},
                {
                    "pid": 222,
                    "auxiliary": {"phys_footprint": 241172480, "phys_footprint_peak": 1249902592},
                },
            ]
        }

        def _write_payload(argv):
            with open(argv[3], "w") as f:
                json.dump(payload, f)
            return ""

        with patch("lightcycle.adapters.machine._run", side_effect=_write_payload):
            result = _macos_footprint_kb([111, 222])

        self.assertEqual(result, {222: (235520.0, 1220608.0)})

    def test_returns_empty_when_the_payload_carries_a_null_process_list(self):
        def _write_payload(argv):
            with open(argv[3], "w") as f:
                json.dump({"processes": None}, f)
            return ""

        with patch("lightcycle.adapters.machine._run", side_effect=_write_payload):
            self.assertEqual(_macos_footprint_kb([111]), {})

    def test_returns_none_when_the_subprocess_call_fails(self):
        with patch("lightcycle.adapters.machine._run", return_value=None):
            self.assertIsNone(_macos_footprint_kb([111]))

    def test_removes_the_temp_file_after_returning(self):
        captured = {}

        def _write_payload(argv):
            captured["path"] = argv[3]
            with open(argv[3], "w") as f:
                json.dump({"processes": []}, f)
            return ""

        with patch("lightcycle.adapters.machine._run", side_effect=_write_payload):
            _macos_footprint_kb([111])

        self.assertFalse(os.path.exists(captured["path"]))


class TestMacosPoolFootprintKb(unittest.TestCase):
    def test_empty_workers_returns_zero_without_calling_worker_pids(self):
        with patch("lightcycle.adapters.machine._worker_pids") as mock_worker_pids:
            self.assertEqual(_macos_pool_footprint_kb([]), (0.0, None))
        mock_worker_pids.assert_not_called()

    def test_returns_none_none_when_every_group_is_empty(self):
        with patch("lightcycle.adapters.machine._worker_pids", return_value=[[], []]):
            self.assertEqual(_macos_pool_footprint_kb(["a", "b"]), (None, None))

    def test_returns_none_none_when_the_footprint_read_fails_entirely(self):
        with patch("lightcycle.adapters.machine._worker_pids", return_value=[[111]]), \
             patch("lightcycle.adapters.machine._macos_footprint_kb", return_value=None):
            self.assertEqual(_macos_pool_footprint_kb(["a"]), (None, None))

    def test_sums_each_workers_pids_and_returns_the_max_peak_across_workers(self):
        readings = {111: (100.0, 300.0), 112: (50.0, 100.0), 211: (200.0, 900.0)}
        with patch(
            "lightcycle.adapters.machine._worker_pids", return_value=[[111, 112], [211]]
        ), patch("lightcycle.adapters.machine._macos_footprint_kb", return_value=readings):
            pool_kb, peak_kb = _macos_pool_footprint_kb(["a", "b"])

        self.assertEqual(pool_kb, 350.0)
        self.assertEqual(peak_kb, 900.0)


class TestSmapsRollupPssKb(unittest.TestCase):
    def test_returns_pss_only_when_swap_pss_absent(self):
        text = "Rss:  1000 kB\nPss:  800 kB\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertEqual(_smaps_rollup_pss_kb(123), 800.0)

    def test_returns_pss_plus_swap_pss_when_both_present(self):
        text = "Pss:  800 kB\nSwapPss:  200 kB\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertEqual(_smaps_rollup_pss_kb(123), 1000.0)

    def test_returns_none_when_the_file_does_not_exist(self):
        with patch("builtins.open", side_effect=OSError("no such file")):
            self.assertIsNone(_smaps_rollup_pss_kb(123))

    def test_returns_none_when_the_pss_line_is_absent(self):
        text = "Rss:  1000 kB\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertIsNone(_smaps_rollup_pss_kb(123))


class TestStatusVmHwmKb(unittest.TestCase):
    def test_returns_the_parsed_value(self):
        text = "VmHWM:  4096 kB\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertEqual(_status_vm_hwm_kb(123), 4096.0)

    def test_returns_none_when_the_file_does_not_exist(self):
        with patch("builtins.open", side_effect=OSError("no such file")):
            self.assertIsNone(_status_vm_hwm_kb(123))

    def test_returns_none_when_the_vmhwm_line_is_absent(self):
        text = "VmRSS:  4096 kB\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertIsNone(_status_vm_hwm_kb(123))


class TestLinuxPidFootprintKb(unittest.TestCase):
    def test_returns_current_and_peak_when_both_reads_succeed(self):
        with patch("lightcycle.adapters.machine._smaps_rollup_pss_kb", return_value=800.0), \
             patch("lightcycle.adapters.machine._status_vm_hwm_kb", return_value=4096.0):
            self.assertEqual(_linux_pid_footprint_kb(123), (800.0, 4096.0))

    def test_returns_none_when_the_current_read_fails(self):
        with patch("lightcycle.adapters.machine._smaps_rollup_pss_kb", return_value=None), \
             patch("lightcycle.adapters.machine._status_vm_hwm_kb", return_value=4096.0):
            self.assertIsNone(_linux_pid_footprint_kb(123))

    def test_peak_half_is_none_when_the_vmhwm_read_fails_but_current_succeeds(self):
        with patch("lightcycle.adapters.machine._smaps_rollup_pss_kb", return_value=800.0), \
             patch("lightcycle.adapters.machine._status_vm_hwm_kb", return_value=None):
            self.assertEqual(_linux_pid_footprint_kb(123), (800.0, None))


class TestLinuxPoolFootprintKb(unittest.TestCase):
    def test_empty_workers_returns_zero_without_calling_worker_pids(self):
        with patch("lightcycle.adapters.machine._worker_pids") as mock_worker_pids:
            self.assertEqual(_linux_pool_footprint_kb([]), (0.0, None))
        mock_worker_pids.assert_not_called()

    def test_returns_none_none_when_every_group_is_empty(self):
        with patch("lightcycle.adapters.machine._worker_pids", return_value=[[], []]):
            self.assertEqual(_linux_pool_footprint_kb(["a", "b"]), (None, None))

    def test_returns_none_none_when_every_pid_read_fails(self):
        with patch("lightcycle.adapters.machine._worker_pids", return_value=[[111]]), \
             patch("lightcycle.adapters.machine._linux_pid_footprint_kb", return_value=None):
            self.assertEqual(_linux_pool_footprint_kb(["a"]), (None, None))

    def test_sums_each_workers_pids_and_returns_the_max_peak_across_workers(self):
        readings = {111: (100.0, 300.0), 112: (50.0, 100.0), 211: (200.0, 900.0)}
        with patch(
            "lightcycle.adapters.machine._worker_pids", return_value=[[111, 112], [211]]
        ), patch(
            "lightcycle.adapters.machine._linux_pid_footprint_kb", side_effect=readings.get
        ):
            pool_kb, peak_kb = _linux_pool_footprint_kb(["a", "b"])

        self.assertEqual(pool_kb, 350.0)
        self.assertEqual(peak_kb, 900.0)

    def test_partial_peak_failure_within_a_worker_treats_the_missing_peak_as_zero(self):
        readings = {111: (100.0, None)}
        with patch("lightcycle.adapters.machine._worker_pids", return_value=[[111]]), \
             patch(
                 "lightcycle.adapters.machine._linux_pid_footprint_kb", side_effect=readings.get
             ):
            pool_kb, peak_kb = _linux_pool_footprint_kb(["a"])

        self.assertEqual(pool_kb, 100.0)
        self.assertEqual(peak_kb, 0.0)


class TestWorkerPidsGetpgidFallback(unittest.TestCase):
    def test_uses_the_dead_pid_itself_as_pgid_when_getpgid_raises(self):
        worker = Worker(pid=4242)
        captured = {}

        def pid_argv_for(pgid):
            captured["pgid"] = pgid
            return ["ps", "-o", "pid=", "-g", str(pgid)]

        with patch("os.getpgid", side_effect=ProcessLookupError()), \
             patch(
                 "lightcycle.adapters.machine.subprocess.run",
                 return_value=_proc(b"4242\n5000\n"),
             ):
            groups = _worker_pids([worker], pid_argv_for)

        self.assertEqual(captured["pgid"], 4242)
        self.assertEqual(groups, [[4242, 5000]])


class TestMachineAdapterWorktreePids(unittest.TestCase):
    def setUp(self):
        self.adapter = MachineAdapter()

    def test_returns_pids_whose_cwd_is_the_worktree_or_below_it(self):
        out = b"p1234\nfcwd\nn/repo/.worktrees/x\np5678\nfcwd\nn/repo/.worktrees/x/src/deep\n"
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(out),
        ):
            self.assertEqual(self.adapter.worktree_pids("/repo/.worktrees/x"), [1234, 5678])

    def test_omits_pids_whose_cwd_is_elsewhere(self):
        out = (
            b"p62232\nfcwd\nn/\n"
            b"p4321\nfcwd\nn/repo/.worktrees/xylophone\n"
            b"p1234\nfcwd\nn/repo/.worktrees/x\n"
        )
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(out),
        ):
            self.assertEqual(self.adapter.worktree_pids("/repo/.worktrees/x"), [1234])

    def test_returns_empty_list_when_lsof_exits_non_zero(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            return_value=_proc(b"", returncode=1),
        ):
            self.assertEqual(self.adapter.worktree_pids("/repo/.worktrees/x"), [])

    def test_returns_empty_list_when_lsof_is_missing(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            side_effect=OSError("no such command"),
        ):
            self.assertEqual(self.adapter.worktree_pids("/repo/.worktrees/x"), [])

    def test_returns_empty_list_when_nothing_is_found(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(b""),
        ):
            self.assertEqual(self.adapter.worktree_pids("/repo/.worktrees/x"), [])

    def test_asks_lsof_for_current_working_directories_only(self):
        mock_run = MagicMock(return_value=_proc(b""))
        with patch("lightcycle.adapters.machine.subprocess.run", mock_run):
            self.adapter.worktree_pids("/repo/.worktrees/x")

        argv = mock_run.call_args.args[0]
        self.assertEqual(argv[argv.index("-d") + 1], "cwd")
        self.assertNotIn("+D", argv)


class TestMachineAdapterCwdPidsUnder(unittest.TestCase):
    def setUp(self):
        self.adapter = MachineAdapter()

    def test_groups_pids_by_cwd_strictly_below_the_root(self):
        out = (
            b"p1\nfcwd\nn/repo/.worktrees/gone\n"
            b"p2\nfcwd\nn/repo/.worktrees/gone/src\n"
            b"p3\nfcwd\nn/repo/.worktrees/gone\n"
            b"p4\nfcwd\nn/repo/.worktrees\n"
            b"p5\nfcwd\nn/repo/.worktreesx/other\n"
            b"p6\nfcwd\nn/elsewhere\n"
        )
        with patch(
            "lightcycle.adapters.machine.subprocess.run", return_value=_proc(out),
        ):
            found = self.adapter.cwd_pids_under("/repo/.worktrees")

        self.assertEqual(found, {
            "/repo/.worktrees/gone": [1, 3],
            "/repo/.worktrees/gone/src": [2],
        })

    def test_returns_empty_dict_when_lsof_exits_non_zero(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            return_value=_proc(b"", returncode=1),
        ):
            self.assertEqual(self.adapter.cwd_pids_under("/repo/.worktrees"), {})


class TestFakeMachineWorktreePids(unittest.TestCase):
    def test_returns_the_configured_pids_for_the_given_path(self):
        machine = FakeMachine(worktree_pids={"/repo/.worktrees/x": [111, 222]})
        self.assertEqual(machine.worktree_pids("/repo/.worktrees/x"), [111, 222])

    def test_returns_empty_list_for_an_unconfigured_path(self):
        self.assertEqual(FakeMachine().worktree_pids("/repo/.worktrees/x"), [])


class TestFakeMachineSelfRss(unittest.TestCase):
    def test_returns_the_configured_rss(self):
        self.assertEqual(FakeMachine(rss=1234).self_rss(), 1234)

    def test_returns_none_when_no_rss_is_given(self):
        self.assertIsNone(FakeMachine().self_rss())


if __name__ == "__main__":
    unittest.main()
