import unittest

from lightcycle.application.pool import EarlierLogInput, ReadEarlierLogUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


def _step_with_logs(*paths):
    store = FakeStore()
    item = store.create_item("Item", "d")
    step = store.create_step(stage="coder", role="agent", item=item)
    for path in paths:
        store.set_log(step, path)
    return store, step


def _run(store, fs, target, session, offset, max_bytes=1000):
    return ReadEarlierLogUseCase(store, fs, fs).execute(
        EarlierLogInput(target=target, session=session, offset=offset, max_bytes=max_bytes)
    ).chunks


class TestReadEarlierLog(unittest.TestCase):
    def test_a_cursor_at_the_first_line_of_session_one_returns_nothing(self):
        store, step = _step_with_logs("/l/a.log")

        self.assertEqual(_run(store, FakeFs(files={"/l/a.log": b"x\n"}), step, 1, 0), ())

    def test_a_target_that_is_not_a_step_returns_nothing(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        item = store.get_node(step).item

        self.assertEqual(_run(store, FakeFs(), item, 2, 0), ())
        self.assertEqual(_run(store, FakeFs(), "nope", 2, 0), ())

    def test_a_mixed_set_of_present_and_missing_logs_reports_each(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log", "/l/c.log")
        fs = FakeFs(files={"/l/b.log": b"bee\n", "/l/c.log": b"sea\n"})

        chunks = _run(store, fs, step, 3, 0)

        self.assertEqual([c.session.log_path for c in chunks], ["/l/a.log", "/l/b.log"])
        self.assertEqual([c.exists for c in chunks], [False, True])
        self.assertEqual([c.data for c in chunks], [b"", b"bee\n"])

    def test_every_earlier_file_missing_gives_one_absent_chunk_each(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log", "/l/c.log")

        chunks = _run(store, FakeFs(files={"/l/c.log": b"sea\n"}), step, 3, 0)

        self.assertEqual([c.exists for c in chunks], [False, False])
        self.assertEqual([c.data for c in chunks], [b"", b""])

    def test_the_cursor_session_is_read_before_the_offset_first(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        fs = FakeFs(files={"/l/a.log": b"old\n", "/l/b.log": b"one\ntwo\nthree\n"})

        chunks = _run(store, fs, step, 2, 8, max_bytes=4)

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].session.n, chunks[0].data, chunks[0].start), (2, b"two\n", 4))

    def test_reaching_a_session_start_continues_into_the_previous_session(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        fs = FakeFs(files={"/l/a.log": b"old\nolder\n", "/l/b.log": b"one\ntwo\n"})

        chunks = _run(store, fs, step, 2, 4)

        self.assertEqual([(c.session.n, c.data, c.start) for c in chunks],
                         [(1, b"old\nolder\n", 0), (2, b"one\n", 0)])

    def test_one_budget_is_shared_across_sessions(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log", "/l/c.log")
        line = b"x" * 9 + b"\n"
        fs = FakeFs(files={
            "/l/a.log": line * 6,
            "/l/b.log": line * 6,
            "/l/c.log": b"live\n",
        })

        chunks = _run(store, fs, step, 3, 0, max_bytes=100)

        self.assertEqual([c.session.n for c in chunks], [1, 2])
        self.assertEqual(len(chunks[1].data), 60)
        self.assertEqual(chunks[1].start, 0)
        self.assertEqual(len(chunks[0].data), 40)
        self.assertGreater(chunks[0].start, 0)

    def test_a_session_exactly_the_size_of_the_budget_stops_on_its_start(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        fs = FakeFs(files={"/l/a.log": b"12345678\n", "/l/b.log": b"live\n"})

        chunks = _run(store, fs, step, 2, 0, max_bytes=9)

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].session.n, chunks[0].start, len(chunks[0].data)), (1, 0, 9))

    def test_a_line_longer_than_the_budget_is_returned_whole(self):
        store, step = _step_with_logs("/l/a.log", "/l/b.log")
        fs = FakeFs(files={"/l/a.log": b"short\n" + b"y" * 50 + b"\n", "/l/b.log": b"live\n"})

        chunks = _run(store, fs, step, 2, 0, max_bytes=10)

        self.assertEqual(chunks[0].data, b"y" * 50 + b"\n")
        self.assertEqual(chunks[0].start, 6)


if __name__ == "__main__":
    unittest.main()
