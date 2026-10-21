class AccrualGatesUseCase:
    def __init__(self, usage_gate, gh_call_gate):
        self._usage_gate = usage_gate
        self._gh_call_gate = gh_call_gate

    def execute(self, now):
        self._usage_gate.execute(now)
        self._gh_call_gate.execute()
