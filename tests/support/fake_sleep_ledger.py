from lightcycle.ports.sleep_ledger import SleepLedgerPort


class FakeSleepLedger(SleepLedgerPort):
    def __init__(self, state=None):
        self._state = dict(state) if state else {}
        self.saves = []

    def load(self):
        return dict(self._state)

    def save(self, state):
        self._state = dict(state)
        self.saves.append(dict(state))
