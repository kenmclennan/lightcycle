import threading
import unittest

from lightcycle.adapters.github_poll_runner import GithubPollRunnerAdapter


class TestGithubPollRunner(unittest.TestCase):
    def test_start_is_refused_while_a_run_is_in_flight(self):
        runner = GithubPollRunnerAdapter()
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
        runner = GithubPollRunnerAdapter()

        def boom():
            raise RuntimeError("boom")

        self.assertTrue(runner.start(boom))
        runner._thread.join(5)

        self.assertFalse(runner.running())
        self.assertTrue(runner.start(lambda: None))


if __name__ == "__main__":
    unittest.main()
