import os
import subprocess
import unittest
from unittest.mock import MagicMock, mock_open, patch

from lightcycle.adapters.machine import (
    MachineAdapter, _headroom_linux, _headroom_macos, _linux_memory_pressure,
    _macos_memory_pressure,
)
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


class TestMacosMemoryPressure(unittest.TestCase):
    def test_returns_free_fraction_inverted_from_the_reported_percentage(self):
        stdout = (
            b"the memory_pressure tool is depre...\n"
            b"System-wide memory free percentage: 49%\n"
        )
        with patch("lightcycle.adapters.machine.subprocess.run", return_value=_proc(stdout)):
            self.assertAlmostEqual(_macos_memory_pressure(), 0.51)

    def test_returns_none_when_the_subprocess_call_fails(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            side_effect=OSError("no such command"),
        ):
            self.assertIsNone(_macos_memory_pressure())

    def test_returns_none_when_the_subprocess_call_times_out(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="memory_pressure", timeout=2),
        ):
            self.assertIsNone(_macos_memory_pressure())

    def test_returns_none_when_memory_pressure_exits_non_zero(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            return_value=_proc(b"", returncode=1),
        ):
            self.assertIsNone(_macos_memory_pressure())

    def test_returns_none_when_the_expected_line_is_absent(self):
        with patch(
            "lightcycle.adapters.machine.subprocess.run",
            return_value=_proc(b"some other output\n"),
        ):
            self.assertIsNone(_macos_memory_pressure())


class TestLinuxMemoryPressure(unittest.TestCase):
    def test_returns_avg10_divided_by_100_from_the_full_line(self):
        text = (
            "some avg10=1.11 avg60=2.22 avg300=3.33 total=100\n"
            "full avg10=12.50 avg60=5.00 avg300=1.00 total=200\n"
        )
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertAlmostEqual(_linux_memory_pressure(), 0.125)

    def test_returns_none_when_the_file_does_not_exist(self):
        with patch("builtins.open", side_effect=OSError("no such file")):
            self.assertIsNone(_linux_memory_pressure())

    def test_returns_none_when_no_line_starts_with_full(self):
        text = "some avg10=1.11 avg60=2.22 avg300=3.33 total=100\n"
        with patch("builtins.open", mock_open(read_data=text)):
            self.assertIsNone(_linux_memory_pressure())


class TestHeadroomMacos(unittest.TestCase):
    def test_pool_share_populated_when_pressure_read_fails(self):
        with patch("lightcycle.adapters.machine._macos_memory_pressure", return_value=None), \
             patch("lightcycle.adapters.machine._macos_total_memory_kb", return_value=1000.0), \
             patch("lightcycle.adapters.machine._pool_rss_kb", return_value=100):
            headroom = _headroom_macos([])

        self.assertIsNone(headroom.system_pressure)
        self.assertEqual(headroom.pool_share, 0.1)

    def test_system_pressure_populated_when_rss_read_fails(self):
        with patch("lightcycle.adapters.machine._macos_memory_pressure", return_value=0.4), \
             patch("lightcycle.adapters.machine._macos_total_memory_kb", return_value=None):
            headroom = _headroom_macos([])

        self.assertEqual(headroom.system_pressure, 0.4)
        self.assertIsNone(headroom.pool_share)


class TestHeadroomLinux(unittest.TestCase):
    def test_pool_share_populated_when_pressure_read_fails(self):
        with patch("lightcycle.adapters.machine._linux_memory_pressure", return_value=None), \
             patch(
                 "lightcycle.adapters.machine._proc_meminfo",
                 return_value={"MemTotal": 1000.0},
             ), \
             patch("lightcycle.adapters.machine._pool_rss_kb", return_value=100):
            headroom = _headroom_linux([])

        self.assertIsNone(headroom.system_pressure)
        self.assertEqual(headroom.pool_share, 0.1)

    def test_system_pressure_populated_when_meminfo_read_fails(self):
        with patch("lightcycle.adapters.machine._linux_memory_pressure", return_value=0.3), \
             patch("lightcycle.adapters.machine._proc_meminfo", return_value=None):
            headroom = _headroom_linux([])

        self.assertEqual(headroom.system_pressure, 0.3)
        self.assertIsNone(headroom.pool_share)


class TestFakeMachineSelfRss(unittest.TestCase):
    def test_returns_the_configured_rss(self):
        self.assertEqual(FakeMachine(rss=1234).self_rss(), 1234)

    def test_returns_none_when_no_rss_is_given(self):
        self.assertIsNone(FakeMachine().self_rss())


if __name__ == "__main__":
    unittest.main()
