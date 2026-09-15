import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from lightcycle.adapters.machine import MachineAdapter
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


class TestFakeMachineSelfRss(unittest.TestCase):
    def test_returns_the_configured_rss(self):
        self.assertEqual(FakeMachine(rss=1234).self_rss(), 1234)

    def test_returns_none_when_no_rss_is_given(self):
        self.assertIsNone(FakeMachine().self_rss())


if __name__ == "__main__":
    unittest.main()
