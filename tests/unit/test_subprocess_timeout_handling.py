import subprocess
import unittest
from unittest import mock

from lightcycle.adapters.workers import process_start_time
from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter
from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.ports.workflow_source import WorkflowSourceError


class FakeConfig:
    def data_root(self):
        return "/nonexistent"


def _timeout(*_args, **_kwargs):
    raise subprocess.TimeoutExpired("git", 1)


class TestProcessStartTime(unittest.TestCase):
    def test_a_timed_out_ps_reads_as_no_start_time(self):
        with mock.patch("lightcycle.adapters.workers.subprocess.run", side_effect=_timeout):
            self.assertIsNone(process_start_time(1234))

    def test_ps_is_called_with_a_timeout(self):
        done = subprocess.CompletedProcess([], 0, stdout=b"Mon Nov  9 10:00:00 2026\n")
        with mock.patch("lightcycle.adapters.workers.subprocess.run", return_value=done) as run:
            self.assertEqual(process_start_time(1234), "Mon Nov  9 10:00:00 2026")
        self.assertIsNotNone(run.call_args.kwargs["timeout"])


class TestWorkflowSourceFetchTimeouts(unittest.TestCase):
    def _adapter(self):
        return WorkflowSourceAdapter(FakeConfig(), WorkflowBundleAdapter())

    def test_a_clone_that_times_out_names_the_url(self):
        with mock.patch("lightcycle.adapters.workflow_source.subprocess.run", side_effect=_timeout):
            with self.assertRaises(WorkflowSourceError) as caught:
                self._adapter().fetch("https://example.test/acme.git", None)
        self.assertIn("could not clone https://example.test/acme.git", str(caught.exception))

    def test_a_checkout_that_times_out_names_the_ref_not_the_clone(self):
        def run(cmd, **kwargs):
            if "clone" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise subprocess.TimeoutExpired(cmd, 1)

        with mock.patch("lightcycle.adapters.workflow_source.subprocess.run", side_effect=run):
            with self.assertRaises(WorkflowSourceError) as caught:
                self._adapter().fetch("https://example.test/acme.git", "v1")
        message = str(caught.exception)
        self.assertIn("ref 'v1'", message)
        self.assertNotIn("clone", message)

    def test_a_rev_parse_that_times_out_names_the_checkout(self):
        def run(cmd, **kwargs):
            if "rev-parse" in cmd:
                raise subprocess.TimeoutExpired(cmd, 1)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch("lightcycle.adapters.workflow_source.subprocess.run", side_effect=run):
            with self.assertRaises(WorkflowSourceError) as caught:
                self._adapter().fetch("https://example.test/acme.git", None)
        self.assertIn("could not resolve HEAD", str(caught.exception))
