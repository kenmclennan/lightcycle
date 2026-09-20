import os
import subprocess
import tempfile
import time
import unittest

from lightcycle.adapters import workers as wk

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


def _spawn_leader_with_child():
    leader = subprocess.Popen(["python3", "-c", LEADER], start_new_session=True)
    time.sleep(0.6)
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
