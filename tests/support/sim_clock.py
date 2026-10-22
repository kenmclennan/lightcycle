import datetime


class SimClock:
    def __init__(self, start=10000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now

    def sleep(self, seconds):
        self.advance(seconds)

    def iso(self):
        stamp = datetime.datetime.fromtimestamp(self.now, tz=datetime.timezone.utc)
        return stamp.isoformat()
