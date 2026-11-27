import os
import tempfile
import unittest

from lightcycle.adapters import step_scratch
from lightcycle.adapters import workers as wk


class TestScratchDir(unittest.TestCase):
    def test_scratch_dir_is_under_data_root_keyed_by_spawn_id(self):
        self.assertEqual(
            step_scratch.scratch_dir("/data", "abcd1234"), os.path.join("/data", "scratch", "abcd1234")
        )

    def test_create_scratch_makes_a_private_folder(self):
        with tempfile.TemporaryDirectory() as root:
            path = step_scratch.create_scratch(root, "abcd1234")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)


class TestTaggedPids(unittest.TestCase):
    def test_tagged_pids_matches_exact_and_nested_tmpdir_not_sibling(self):
        a, b = "/x/scratch/aaaa1111", "/x/scratch/bbbb2222"
        listing = [
            (100, [a]),
            (101, [a + "/x"]),
            (102, [a + "2"]),
            (103, [b]),
            (104, []),
        ]
        result = step_scratch.tagged_pids(
            [a], scan=lambda: listing, own_pid=1, own_pgid=-5
        )
        self.assertEqual(sorted(result[a]), [100, 101])

    def test_tagged_pids_never_returns_own_pid_or_own_group(self):
        a = "/x/scratch/aaaa1111"
        listing = [(os.getpid(), [a]), (1, [a]), (0, [a]), (os.getppid(), [a])]
        result = step_scratch.tagged_pids(
            [a], scan=lambda: listing, own_pgid=os.getpgid(0)
        )
        self.assertEqual(result[a], [])

    def test_scan_failure_returns_nothing_and_deletes_nothing(self):
        self.assertIsNone(step_scratch.tagged_pids(["/x"], scan=lambda: None))
        with tempfile.TemporaryDirectory() as root:
            folder = step_scratch.create_scratch(root, "dead0001")
            wk.write_workers(root, [{"spawnid": "dead0001", "pid": 2 ** 22 + 7}])
            dropped = wk.prune_workers(
                root, 0, alive=lambda pid, started: False, tagged=lambda paths: None
            )
            self.assertEqual(dropped, 0)
            self.assertTrue(os.path.isdir(folder))
            self.assertEqual(len(wk.workers_state(root)), 1)


class TestParsing(unittest.TestCase):
    def test_ps_token_requires_whitespace_before(self):
        found = step_scratch._TMPDIR_TOKEN.findall("/usr/bin/python3 -c x TMPDIR=/a/b FOO=1 XTMPDIR=/no")
        self.assertEqual(found, ["/a/b"])


if __name__ == "__main__":
    unittest.main()
