import threading
from concurrent.futures import ThreadPoolExecutor


class ReportRunner:
    def __init__(self, build_store, make_use_case):
        self._build_store = build_store
        self._make_use_case = make_use_case
        self._lock = threading.Lock()
        self._executor = None
        self._store = None
        self._closed = False

    def execute(self, request):
        return self._submit(self._run, request).result()

    def close(self):
        with self._lock:
            executor = self._executor
            self._executor = None
            self._closed = True
        if executor is None:
            return
        executor.submit(self._close_store).result()
        executor.shutdown()

    def _submit(self, fn, *args):
        with self._lock:
            if self._closed:
                raise RuntimeError("report runner is closed")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="report")
            return self._executor.submit(fn, *args)

    def _run(self, request):
        if self._store is None:
            self._store = self._build_store()
        return self._make_use_case(self._store).execute(request)

    def _close_store(self):
        store, self._store = self._store, None
        if store is not None:
            store.close()
