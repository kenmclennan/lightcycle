import contextlib
import io
import threading
import unittest

from lightcycle.adapters.github_poll_runner import GithubPollRunnerAdapter
from tests.support.fake_fs import FakeFs


class TestGithubPollRunner(unittest.TestCase):
    def test_start_is_refused_while_a_run_is_in_flight(self):
        runner = GithubPollRunnerAdapter(FakeFs())
        release = threading.Event()
        started = threading.Event()

        def work():
            started.set()
            release.wait(5)

        self.assertTrue(runner.start(work))
        started.wait(5)
        self.assertTrue(runner.running())
        self.assertFalse(runner.start(lambda: None))
        release.set()
        runner._thread.join(5)
        self.assertFalse(runner.running())
        self.assertTrue(runner.start(lambda: None))

    def test_a_run_that_raises_leaves_the_next_start_allowed(self):
        runner = GithubPollRunnerAdapter(FakeFs())

        def boom():
            raise RuntimeError("boom")

        self.assertTrue(runner.start(boom))
        runner._thread.join(5)

        self.assertFalse(runner.running())
        self.assertTrue(runner.start(lambda: None))


    def test_a_run_that_raises_writes_a_run_log_line_and_the_stderr_warning(self):
        fs = FakeFs()
        runner = GithubPollRunnerAdapter(fs)

        def boom():
            raise RuntimeError("boom")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            runner.start(boom)
            runner._thread.join(5)

        self.assertIn("github poll failed: boom", stderr.getvalue())
        line = fs._files["logs/run.log"].decode("utf-8")
        self.assertIn("github", line)
        self.assertIn("poll raised: boom", line)

    def test_a_worker_log_that_cannot_be_written_does_not_raise_out_of_the_body(self):
        class _Broken:
            def append_run_log(self, text):
                raise OSError("disk full")

        runner = GithubPollRunnerAdapter(_Broken())

        def boom():
            raise RuntimeError("boom")

        with contextlib.redirect_stderr(io.StringIO()):
            runner._body(boom)


if __name__ == "__main__":
    unittest.main()
