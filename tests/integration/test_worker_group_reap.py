import os
import signal
import subprocess
import tempfile
import time
import unittest

from lightcycle.adapters import workers as wk

IGNORER = (
    "import signal,subprocess,sys,time;"
    "subprocess.Popen([sys.executable,'-c',"
    "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(300)']);"
    "time.sleep(0.5)"
)
LEADER = "import subprocess,time;subprocess.Popen(['sleep','300']);time.sleep(0.2)"


REAP_DEADLINE = 30.0
POLL_INTERVAL = 0.1


def _ps_snapshot():
    started = time.monotonic()
    out = subprocess.run(
        ["ps", "-A", "-o", "pid=,ppid=,pgid=,stat="], capture_output=True, text=True
    )
    elapsed = time.monotonic() - started
    rows = []
    for line in out.stdout.splitlines():
        fields = line.split()
        if len(fields) == 4:
            rows.append(dict(zip(("pid", "ppid", "pgid", "stat"), fields)))
    return rows, elapsed


def _live_group_rows(rows, pgid):
    return [
        r for r in rows if r["pgid"] == str(pgid) and not r["stat"].startswith("Z")
    ]


def _in_group(pgid):
    rows, _ = _ps_snapshot()
    return [r["pid"] for r in _live_group_rows(rows, pgid)]


def _assert_group_reaped(test, pgid, message, timeout=REAP_DEADLINE):
    started = time.monotonic()
    polls = 0
    slowest = 0.0
    while True:
        rows, took = _ps_snapshot()
        polls += 1
        slowest = max(slowest, took)
        survivors = _live_group_rows(rows, pgid)
        if not survivors:
            return
        if time.monotonic() - started >= timeout:
            break
        time.sleep(POLL_INTERVAL)
    detail = "\n".join(
        "pid=%(pid)s ppid=%(ppid)s pgid=%(pgid)s stat=%(stat)s" % r for r in survivors
    )
    test.fail(
        "%s: group %s not empty after %.2fs, %d polls, slowest ps %.3fs; survivors:\n%s"
        % (message, pgid, time.monotonic() - started, polls, slowest, detail)
    )


def _spawn_leader_with_child(code=LEADER):
    leader = subprocess.Popen(["python3", "-c", code], start_new_session=True)
    time.sleep(1.0 if code is not LEADER else 0.6)
    leader.wait()
    return leader.pid


class TestWorkerGroupReap(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "logs"), exist_ok=True)
        self.strays = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for pgid in self.strays:
            try:
                os.killpg(pgid, 15)
            except OSError:
                pass

    def _register(self, pid, started=None):
        wk.register_worker(self.root, {"spawnid": "sp-%s" % pid, "role": "agent",
                                       "pid": pid, "pid_started": started, "step": None})

    def test_prune_reaps_a_dead_workers_orphaned_child(self):
        pid = _spawn_leader_with_child()
        self.strays.append(pid)
        self.assertTrue(_in_group(pid), "probe did not leave an orphan; test is not exercising the bug")
        self._register(pid)

        wk.prune_workers(self.root, keep_dead=0)

        _assert_group_reaped(self, pid, "orphaned child survived prune_workers")

    def test_kill_reaps_a_dead_leaders_orphaned_child(self):
        pid = _spawn_leader_with_child()
        self.strays.append(pid)
        self.assertTrue(_in_group(pid), "probe did not leave an orphan; test is not exercising the bug")

        wk.kill(pid)

        _assert_group_reaped(self, pid, "orphaned child survived wk.kill(pid)")

    def test_a_live_pid_is_never_signalled(self):
        live = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.addCleanup(live.kill)
        self.assertFalse(wk.reap_worker_group(live.pid))
        time.sleep(0.3)
        self.assertIsNone(live.poll(), "reap killed a live process group")

    def test_a_recycled_pid_is_never_signalled(self):
        live = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.addCleanup(live.kill)
        self._register(live.pid, started="1")
        self.assertFalse(
            wk.worker_alive(live.pid, "1"),
            "fixture is wrong: a mismatched pid_started should read as not-this-worker",
        )

        wk.prune_workers(self.root, keep_dead=0)

        time.sleep(0.3)
        self.assertIsNone(live.poll(), "prune signalled a recycled pid's group")

    def test_reap_is_idempotent_and_quiet_on_an_empty_group(self):
        pid = _spawn_leader_with_child()
        self.strays.append(pid)
        self.assertTrue(wk.reap_worker_group(pid))
        _assert_group_reaped(
            self, pid, "orphaned child was not reaped by the OS within the deadline"
        )
        self.assertFalse(wk.reap_worker_group(pid))


    def test_reap_wait_failure_reports_survivors_and_omits_exited_pids(self):
        survivor = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.addCleanup(survivor.kill)
        exited = subprocess.Popen(["true"])
        exited.wait()

        with self.assertRaises(AssertionError) as ctx:
            _assert_group_reaped(self, survivor.pid, "still here", timeout=0.3)

        text = str(ctx.exception)
        self.assertIn("still here", text)
        self.assertIn("polls", text)
        self.assertIn("slowest ps", text)
        self.assertRegex(text, r"after \d+\.\d+s")
        self.assertIn(
            "pid=%d ppid=%d pgid=%d" % (survivor.pid, os.getpid(), survivor.pid), text
        )
        self.assertRegex(text, r"stat=\S+")
        self.assertNotIn("pid=%d " % exited.pid, text)

    def _spawn_ignorer(self):
        pid = _spawn_leader_with_child(IGNORER)
        self.strays.append(pid)
        self.assertTrue(_in_group(pid), "fixture left no child in the group")
        return pid

    def _entry(self, pid):
        return [w for w in wk.workers_state(self.root) if w["pid"] == pid]

    def test_prune_sigkills_a_term_ignoring_child_after_the_grace(self):
        pid = self._spawn_ignorer()
        self._register(pid)

        wk.prune_workers(self.root, keep_dead=5, grace_seconds=60, now=lambda: 1000.0)

        time.sleep(0.5)
        self.assertTrue(_in_group(pid))
        self.assertEqual(self._entry(pid)[0]["reap_term_at"], 1000.0)

        wk.prune_workers(self.root, keep_dead=5, grace_seconds=60, now=lambda: 1061.0)

        _assert_group_reaped(self, pid, "TERM-ignoring child survived the grace")

    def test_prune_does_not_sigkill_inside_the_grace(self):
        pid = self._spawn_ignorer()
        self._register(pid)

        wk.prune_workers(self.root, keep_dead=5, grace_seconds=60, now=lambda: 1000.0)
        wk.prune_workers(self.root, keep_dead=5, grace_seconds=60, now=lambda: 1001.0)

        time.sleep(0.5)
        self.assertTrue(_in_group(pid), "child was killed inside the grace")

    def test_a_dead_workers_entry_is_kept_while_its_group_is_live(self):
        live = self._spawn_ignorer()
        empty = subprocess.Popen(["true"], start_new_session=True)
        empty.wait()
        self._register(live)
        self._register(empty.pid)

        dropped = wk.prune_workers(self.root, keep_dead=0, grace_seconds=60, now=lambda: 1000.0)

        self.assertEqual(dropped, 1)
        self.assertEqual(len(self._entry(live)), 1)
        self.assertEqual(self._entry(empty.pid), [])

        wk.prune_workers(self.root, keep_dead=0, grace_seconds=60, now=lambda: 1100.0)
        _assert_group_reaped(self, live, "TERM-ignoring child survived the grace")
        wk.prune_workers(self.root, keep_dead=0, grace_seconds=60, now=lambda: 1101.0)

        self.assertEqual(self._entry(live), [])

    def test_a_stopped_child_is_ended(self):
        pid = self._spawn_ignorer()
        for row in _live_group_rows(_ps_snapshot()[0], pid):
            os.kill(int(row["pid"]), signal.SIGSTOP)
        self._register(pid)

        wk.prune_workers(self.root, keep_dead=5, grace_seconds=0, now=lambda: 1000.0)
        wk.prune_workers(self.root, keep_dead=5, grace_seconds=0, now=lambda: 1001.0)

        _assert_group_reaped(self, pid, "stopped child survived")
