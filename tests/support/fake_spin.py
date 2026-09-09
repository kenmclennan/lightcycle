from lightcycle.domain.pool.spin_ledger import SpinLedger


class FakeSpinPort:
    def __init__(self, state=None):
        self._ledger = SpinLedger.from_state(state or {})

    def load(self):
        return self._ledger

    def update(self, mutate):
        self._ledger = mutate(self._ledger)
        return self._ledger
