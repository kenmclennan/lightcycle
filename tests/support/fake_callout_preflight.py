class FakeCalloutPreflight:
    def __init__(self, errors=None):
        self._errors = errors or {}
        self.calls = []

    def check(self, callout, context):
        self.calls.append((callout.id, context))
        return list(self._errors.get(callout.id, []))
