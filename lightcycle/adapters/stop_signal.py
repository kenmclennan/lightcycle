import os
import signal
import time

ACK = b"stop requested - finishing the current tick (Ctrl-C again to force)\n"


class StopSignal:
    def __init__(self):
        self.requested = False
        self._sleeping = False
        self._prior = {}

    def handle(self, signum, frame=None):
        if self._sleeping:
            raise KeyboardInterrupt
        if self.requested and signum == signal.SIGINT:
            raise KeyboardInterrupt
        if self.requested:
            return
        self.requested = True
        os.write(2, ACK)

    def pause(self, seconds):
        self._sleeping = True
        try:
            if self.requested:
                return
            time.sleep(seconds)
        finally:
            self._sleeping = False

    def install(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._prior[signum] = signal.getsignal(signum)
            signal.signal(signum, self.handle)

    def restore(self):
        for signum, prior in self._prior.items():
            signal.signal(signum, prior)
        self._prior = {}
