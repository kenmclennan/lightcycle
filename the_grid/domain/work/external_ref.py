"""ExternalRef: strips or qualifies a store's id prefix at the repository boundary."""


class ExternalRef:

    def __init__(self, prefix, bead_id):
        self._prefix = prefix
        self._bead_id = bead_id

    @property
    def short(self):
        """Return the id without a leading '<prefix>-'; pass through if absent."""
        p = self._prefix + "-"
        if self._bead_id.startswith(p):
            return self._bead_id[len(p):]
        return self._bead_id

    @staticmethod
    def qualify(prefix, text):
        """Re-add '<prefix>-' if absent; idempotent when already qualified."""
        p = prefix + "-"
        if text.startswith(p):
            return text
        return p + text
