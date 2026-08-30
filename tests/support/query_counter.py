class QueryCounter:
    def __init__(self, conn):
        self.count = 0
        conn.set_trace_callback(self._on_query)

    def _on_query(self, statement):
        self.count += 1

    def reset(self):
        self.count = 0
