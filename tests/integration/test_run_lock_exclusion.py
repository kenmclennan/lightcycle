import multiprocessing
import os
import tempfile
import unittest

from lightcycle.adapters.lock import acquire, holder_pid, lock_path, release

CONTENDERS = 8


def _contend(root, barrier, results):
    barrier.wait()
    acquired, pid, fd = acquire(root)
    results.put((acquired, pid, os.getpid()))
    if acquired:
        barrier.wait()
        release(root, fd)
    else:
        barrier.wait()


class TestRunLockExclusion(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_concurrent_acquirers_leave_exactly_one_holder(self):
        ctx = multiprocessing.get_context("spawn")
        barrier = ctx.Barrier(CONTENDERS)
        results = ctx.Queue()
        procs = [
            ctx.Process(target=_contend, args=(self.root, barrier, results))
            for _ in range(CONTENDERS)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
        got = [results.get() for _ in range(CONTENDERS)]
        winners = [r for r in got if r[0]]
        self.assertEqual(len(winners), 1, "expected exactly one holder, got %d: %s" % (len(winners), got))

    def test_a_stale_pid_file_from_a_dead_holder_does_not_block_acquisition(self):
        with open(lock_path(self.root), "w") as f:
            f.write("999999")
        acquired, pid, fd = acquire(self.root)
        self.assertTrue(acquired)
        self.assertEqual(pid, os.getpid())
        release(self.root, fd)

    def test_a_live_holder_whose_pid_file_is_empty_still_excludes(self):
        acquired, _, fd = acquire(self.root)
        self.assertTrue(acquired)
        with open(lock_path(self.root), "w"):
            pass
        second, _, second_fd = acquire(self.root)
        release(self.root, fd)
        if second:
            release(self.root, second_fd)
        self.assertFalse(second, "a second acquirer got in while the holder's pid file was empty")

    def test_release_does_not_unlink_the_lock_file(self):
        acquired, _, fd = acquire(self.root)
        self.assertTrue(acquired)
        release(self.root, fd)
        self.assertTrue(
            os.path.exists(lock_path(self.root)),
            "release unlinked the lock file, which lets a concurrent acquirer lock a fresh inode",
        )

    def test_release_clears_the_recorded_holder(self):
        acquired, _, fd = acquire(self.root)
        self.assertTrue(acquired)
        release(self.root, fd)
        self.assertIsNone(holder_pid(self.root))

    def test_release_frees_the_lock_for_the_next_acquirer(self):
        acquired, _, fd = acquire(self.root)
        self.assertTrue(acquired)
        release(self.root, fd)
        again, _, fd2 = acquire(self.root)
        self.assertTrue(again)
        release(self.root, fd2)

    def test_holder_pid_is_none_when_nobody_holds_it(self):
        self.assertIsNone(holder_pid(self.root))
