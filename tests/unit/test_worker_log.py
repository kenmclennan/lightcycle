import os
import tempfile
import unittest

from lightcycle.adapters.worker_log import WorkerLogAdapter, iter_lines
from tests.support.fake_fs import FakeFs


class TestReadFrom(unittest.TestCase):
    def test_reads_from_the_start_when_offset_is_zero(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_from(path, 0)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_reads_only_the_bytes_written_since_the_offset(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\n")
        adapter = WorkerLogAdapter(None)
        _data, offset = adapter.read_from(path, 0)
        with open(path, "a") as f:
            f.write("line two\n")
        data, new_offset = adapter.read_from(path, offset)
        self.assertEqual(data, b"line two\n")
        self.assertEqual(new_offset, offset + len(b"line two\n"))

    def test_missing_file_reads_nothing_and_keeps_the_offset(self):
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_from(os.path.join(tempfile.mkdtemp(), "gone.log"), 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 5)

    def test_fake_fs_slices_seeded_content_from_the_offset(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_from("/l/worker.log", len(b"line one\n"))
        self.assertEqual(data, b"line two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_unknown_path_reads_nothing(self):
        fs = FakeFs()
        data, offset = fs.read_from("/l/missing.log", 0)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)


class TestReadTail(unittest.TestCase):
    def test_smaller_than_max_bytes_returns_the_entire_content(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_tail(path, 1024)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_larger_than_max_bytes_returns_only_the_trailing_bytes(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_tail(path, len(b"line two\n"))
        self.assertEqual(data, b"line two\n")
        self.assertNotIn(b"line one", data)
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_offset_lines_up_exactly_with_a_following_read_from(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "w") as f:
            f.write("line one\nline two\n")
        adapter = WorkerLogAdapter(None)
        _data, offset = adapter.read_tail(path, len(b"line two\n"))
        with open(path, "a") as f:
            f.write("line three\n")
        data, new_offset = adapter.read_from(path, offset)
        self.assertEqual(data, b"line three\n")
        self.assertEqual(new_offset, offset + len(b"line three\n"))

    def test_missing_file_reads_nothing_with_zero_offset(self):
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_tail(os.path.join(tempfile.mkdtemp(), "gone.log"), 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)

    def test_mid_line_seek_discards_the_leading_fragment(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        content = b"line one\nline two\nline three\n"
        with open(path, "wb") as f:
            f.write(content)
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_tail(path, 15)
        self.assertEqual(data, b"line three\n")
        self.assertEqual(offset, len(content))

    def test_offset_after_a_mid_line_trim_lines_up_with_a_following_read_from(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        content = b"line one\nline two\nline three\n"
        with open(path, "wb") as f:
            f.write(content)
        adapter = WorkerLogAdapter(None)
        _data, offset = adapter.read_tail(path, 15)
        with open(path, "ab") as f:
            f.write(b"line four\n")
        data, new_offset = adapter.read_from(path, offset)
        self.assertEqual(data, b"line four\n")
        self.assertEqual(new_offset, offset + len(b"line four\n"))

    def test_a_single_line_wider_than_the_window_yields_no_leading_fragment(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        content = b"x" * 100 + b"\n"
        with open(path, "wb") as f:
            f.write(content)
        adapter = WorkerLogAdapter(None)
        data, offset = adapter.read_tail(path, 10)
        self.assertEqual(data, b"")
        self.assertEqual(offset, len(content))

    def test_fake_fs_smaller_than_max_bytes_returns_the_entire_content(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_tail("/l/worker.log", 1024)
        self.assertEqual(data, b"line one\nline two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_larger_than_max_bytes_returns_only_the_trailing_bytes(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        data, offset = fs.read_tail("/l/worker.log", len(b"line two\n"))
        self.assertEqual(data, b"line two\n")
        self.assertEqual(offset, len(b"line one\nline two\n"))

    def test_fake_fs_unknown_path_reads_nothing_with_zero_offset(self):
        fs = FakeFs()
        data, offset = fs.read_tail("/l/missing.log", 5)
        self.assertEqual(data, b"")
        self.assertEqual(offset, 0)

    def test_fake_fs_mid_line_seek_discards_the_leading_fragment(self):
        content = b"line one\nline two\nline three\n"
        fs = FakeFs(files={"/l/worker.log": content})
        data, offset = fs.read_tail("/l/worker.log", 15)
        self.assertEqual(data, b"line three\n")
        self.assertEqual(offset, len(content))


class TestIterLines(unittest.TestCase):
    def test_module_level_yields_decoded_lines_in_order(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "wb") as f:
            f.write(b"line one\nline two\nline three\n")
        self.assertEqual(list(iter_lines(path)), ["line one\n", "line two\n", "line three\n"])

    def test_module_level_missing_path_yields_nothing(self):
        root = tempfile.mkdtemp()
        self.assertEqual(list(iter_lines(os.path.join(root, "gone.log"))), [])

    def test_module_level_falsy_path_yields_nothing(self):
        self.assertEqual(list(iter_lines(None)), [])
        self.assertEqual(list(iter_lines("")), [])

    def test_module_level_replaces_invalid_utf8_bytes(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "wb") as f:
            f.write(b"good line\n\xff\xfe bad bytes\nlast line\n")
        lines = list(iter_lines(path))
        self.assertEqual(lines[0], "good line\n")
        self.assertIn("�", lines[1])
        self.assertEqual(lines[2], "last line\n")

    def test_adapter_yields_decoded_lines(self):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "worker.log")
        with open(path, "wb") as f:
            f.write(b"line one\nline two\n")
        self.assertEqual(list(WorkerLogAdapter(None).iter_lines(path)), ["line one\n", "line two\n"])

    def test_adapter_missing_path_yields_nothing(self):
        root = tempfile.mkdtemp()
        adapter = WorkerLogAdapter(None)
        self.assertEqual(list(adapter.iter_lines(os.path.join(root, "gone.log"))), [])

    def test_fake_fs_yields_seeded_lines(self):
        fs = FakeFs(files={"/l/worker.log": b"line one\nline two\n"})
        self.assertEqual(list(fs.iter_lines("/l/worker.log")), ["line one\n", "line two\n"])

    def test_fake_fs_unknown_path_yields_nothing(self):
        fs = FakeFs()
        self.assertEqual(list(fs.iter_lines("/l/missing.log")), [])


if __name__ == "__main__":
    unittest.main()
