import sys
import threading

from lightcycle.ports.github_poll_runner import GithubPollRunnerPort


class GithubPollRunnerAdapter(GithubPollRunnerPort):
    def __init__(self):
        self._thread = None
        self._lock = threading.Lock()

    def _body(self, fn):
        try:
            fn()
        except Exception as e:
            sys.stderr.write("warning: github poll failed: %s\n" % e)

    def start(self, fn):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._thread = threading.Thread(target=self._body, args=(fn,), daemon=True)
            self._thread.start()
            return True

    def join(self):
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join()

    def running(self):
        with self._lock:
            return self._thread is not None and self._thread.is_alive()
