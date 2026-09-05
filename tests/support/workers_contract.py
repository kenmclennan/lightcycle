import time


class WorkersContractBase:
    def make_workers(self):
        raise NotImplementedError

    def _seeded_pid(self, w, spawnid):
        for entry in w.workers_state():
            if entry.get("spawnid") == spawnid:
                return entry["pid"]
        raise AssertionError("no seeded worker tagged %r" % spawnid)

    def test_write_workers_and_workers_state_round_trip(self):
        w = self.make_workers()
        workers = [
            {"spawnid": "w1", "role": "coder", "pid": 1, "step": None},
            {"spawnid": "w2", "role": "coder", "pid": 2, "step": None},
        ]
        w.write_workers(workers)
        self.assertEqual(w.workers_state(), workers)

    def test_set_step_then_step_for_returns_it(self):
        w = self.make_workers()
        w.write_workers([{"spawnid": "w1", "role": "coder", "pid": 1, "step": None}])
        w.set_step("w1", "review")
        self.assertEqual(w.step_for("w1"), "review")

    def test_step_for_unknown_spawnid_returns_none(self):
        w = self.make_workers()
        w.write_workers([{"spawnid": "w1", "role": "coder", "pid": 1, "step": None}])
        self.assertIsNone(w.step_for("unknown"))

    def test_pid_alive_true_for_the_seeded_alive_worker(self):
        w = self.make_workers()
        self.assertTrue(w.pid_alive(self._seeded_pid(w, "_alive_seed")))

    def test_pid_alive_false_for_the_seeded_dead_worker(self):
        w = self.make_workers()
        self.assertFalse(w.pid_alive(self._seeded_pid(w, "_dead_seed")))

    def test_kill_makes_pid_alive_eventually_false(self):
        w = self.make_workers()
        pid = self._seeded_pid(w, "_alive_seed")
        self.assertTrue(w.pid_alive(pid))
        w.kill(pid)
        deadline = time.time() + 5
        while time.time() < deadline and w.pid_alive(pid):
            w.reap()
            time.sleep(0.05)
        self.assertFalse(w.pid_alive(pid))

    def test_prune_workers_drops_oldest_dead_beyond_keep_dead(self):
        w = self.make_workers()
        alive_pid = self._seeded_pid(w, "_alive_seed")
        dead_pid = self._seeded_pid(w, "_dead_seed")
        workers = [
            {"spawnid": "dead0", "pid": dead_pid, "step": None},
            {"spawnid": "dead1", "pid": dead_pid, "step": None},
            {"spawnid": "live", "pid": alive_pid, "step": None},
            {"spawnid": "dead2", "pid": dead_pid, "step": None},
        ]
        w.write_workers(workers)
        dropped = w.prune_workers(keep_dead=1)
        self.assertEqual(dropped, 2)
        remaining = {entry["spawnid"] for entry in w.workers_state()}
        self.assertEqual(remaining, {"live", "dead2"})

    def test_mark_checked_only_affects_the_matching_worker(self):
        w = self.make_workers()
        w.write_workers([
            {"spawnid": "w1", "role": "coder", "pid": 1, "step": None, "checked": False},
            {"spawnid": "w2", "role": "coder", "pid": 2, "step": None, "checked": False},
        ])
        w.mark_checked("w1")
        state = {entry["spawnid"]: entry["checked"] for entry in w.workers_state()}
        self.assertTrue(state["w1"])
        self.assertFalse(state["w2"])
