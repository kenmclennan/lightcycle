import multiprocessing
import os
import tempfile
import unittest

from lightcycle.adapters.sqlite_store import SqliteStore
from lightcycle.config import Config
from lightcycle.domain.work import NodeSpec

_CTX = multiprocessing.get_context("fork")


def _make_root(shortcode="GRID"):
    root = tempfile.mkdtemp()
    with open(os.path.join(root, "config"), "w") as f:
        f.write("shortcode: %s\n" % shortcode)
    return root


def _store_for(root, spawn_id=None):
    environ = {"LC_HOME": root, "LC_CONFIG": os.path.join(root, "config")}
    if spawn_id is not None:
        environ["LC_SPAWNID"] = spawn_id
    return SqliteStore(Config(environ=environ))


def _successor_spec(step_id):
    return NodeSpec(title="review: x", step="review", role="reviewer", deps=(step_id,))


def _seed_claimed(root, spawn_id):
    store = _store_for(root, spawn_id)
    store.create_step("build: x", step="build", role="coder")
    step_id = store.claim_ready("coder").id
    store.disconnect()
    return step_id


def _claim_worker(root, spawn_id, barrier, q):
    try:
        store = _store_for(root, spawn_id)
        barrier.wait()
        node = store.claim_ready("coder")
        q.put((spawn_id, node.id if node else None))
        store.disconnect()
    except Exception as exc:
        q.put((spawn_id, "ERROR: %s" % exc))


def _complete_worker(root, spawn_id, expected_assignee, step_id, barrier, q):
    try:
        store = _store_for(root, spawn_id)
        barrier.wait()
        won, new_id = store.complete_step_atomic(
            step_id, "done", expected_assignee, _successor_spec(step_id))
        q.put((spawn_id, won, new_id))
        store.disconnect()
    except Exception as exc:
        q.put((spawn_id, "ERROR", str(exc)))


class TestAtomicClaim(unittest.TestCase):
    def test_concurrent_claim_yields_exactly_one_winner(self):
        root = _make_root()
        seed = _store_for(root)
        step_id = seed.create_step("build: x", step="build", role="coder")
        seed.disconnect()

        n = 8
        barrier = _CTX.Barrier(n)
        q = _CTX.Queue()
        procs = [
            _CTX.Process(target=_claim_worker, args=(root, "w%d" % i, barrier, q))
            for i in range(n)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)

        results = [q.get(timeout=30) for _ in range(n)]
        self.assertTrue(all(not str(tid).startswith("ERROR") for _, tid in results), results)
        winners = [spawn for spawn, tid in results if tid == step_id]
        self.assertEqual(len(winners), 1, "expected one winner, got %r" % winners)

        after = _store_for(root)
        node = after.get_node(step_id)
        self.assertEqual(node.state, "in_progress")
        self.assertEqual(node.claimed_by, winners[0])


class TestAtomicComplete(unittest.TestCase):
    def test_concurrent_complete_files_exactly_one_successor(self):
        root = _make_root()
        step_id = _seed_claimed(root, "A")

        barrier = _CTX.Barrier(2)
        q = _CTX.Queue()
        procs = [
            _CTX.Process(target=_complete_worker, args=(root, "A", "A", step_id, barrier, q))
            for _ in range(2)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)

        results = [q.get(timeout=30) for _ in range(2)]
        self.assertNotIn("ERROR", [r[1] for r in results], results)
        wins = [r for r in results if r[1] is True]
        self.assertEqual(len(wins), 1, "expected one winner, got %r" % results)

        after = _store_for(root)
        parent = after.get_node(step_id).parent
        successors = [s for s in after.steps_at_step("review") if s.parent == parent]
        self.assertEqual(len(successors), 1)
        self.assertEqual(after.get_node(step_id).state, "done")

    def test_mismatched_expected_assignee_is_fenced(self):
        root = _make_root()
        step_id = _seed_claimed(root, "A")
        store = _store_for(root, "B")
        won, new_id = store.complete_step_atomic(step_id, "done", "B", _successor_spec(step_id))
        self.assertFalse(won)
        self.assertIsNone(new_id)
        self.assertEqual(store.get_node(step_id).state, "in_progress")
        self.assertEqual(store.steps_at_step("review"), [])

    def test_empty_expected_assignee_completes_an_assigned_step(self):
        root = _make_root()
        step_id = _seed_claimed(root, "A")
        store = _store_for(root)
        won, new_id = store.complete_step_atomic(step_id, "done", "", _successor_spec(step_id))
        self.assertTrue(won)
        self.assertIsNotNone(new_id)
        self.assertEqual(store.get_node(step_id).state, "done")

    def test_reclaim_fences_the_stale_worker_and_the_reclaimer_completes(self):
        root = _make_root()
        step_id = _seed_claimed(root, "A")
        store_a = _store_for(root, "A")
        store_a.reclaim(step_id)

        store_b = _store_for(root, "B")
        reclaimed = store_b.claim_ready("coder")
        self.assertEqual(reclaimed.id, step_id)
        self.assertEqual(store_b.get_node(step_id).claimed_by, "B")

        stale_won, stale_new = store_a.complete_step_atomic(
            step_id, "done", "A", _successor_spec(step_id))
        self.assertFalse(stale_won)
        self.assertIsNone(stale_new)
        self.assertEqual(store_b.get_node(step_id).state, "in_progress")

        fresh_won, fresh_new = store_b.complete_step_atomic(
            step_id, "done", "B", _successor_spec(step_id))
        self.assertTrue(fresh_won)
        self.assertIsNotNone(fresh_new)
        self.assertEqual(len(store_b.steps_at_step("review")), 1)


if __name__ == "__main__":
    unittest.main()
