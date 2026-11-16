import datetime


class SimClock:
    def __init__(self, start=10000.0):
        self.now = float(start)
        self.asleep = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now

    def suspend(self, seconds):
        self.now += seconds
        self.asleep += seconds
        return self.now

    def awake(self):
        return self.now - self.asleep

    def sleep(self, seconds):
        self.advance(seconds)

    def iso(self):
        stamp = datetime.datetime.fromtimestamp(self.now, tz=datetime.timezone.utc)
        return stamp.isoformat()
