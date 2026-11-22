import os
import stat
import tempfile
import time
import unittest

from lightcycle.adapters.run_groups import RunGroupsAdapter
from lightcycle.adapters.script_runner import ScriptRunnerAdapter
from lightcycle.config import Config
from lightcycle.domain.work import State
from tests.support.callout_rig import CalloutRig, callout


class TestCalloutThroughTheRealRunner(unittest.TestCase):
    def test_a_real_script_response_lands_in_the_record(self):
        directory = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        script = os.path.join(directory, "callout.sh")
        with open(script, "w") as f:
            f.write(
                "#!/bin/sh\ncat >/dev/null\n"
                'echo \'{"status":"ok","artifacts":[{"label":"Open","kind":"link",'
                '"value":"myapp://open?x=1"}]}\'\n')
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        runner = ScriptRunnerAdapter(
            Config(environ={"LC_HOME": home, "LC_WORKER_HISTORY": "20"}), RunGroupsAdapter())
        real = callout("a", "pr")
        real = type(real)(
            id="a", command=script, subject="pr", principal_outputs=("code",), wait=False,
            timeout=30)
        rig = CalloutRig([real], runner=runner)
        step = rig.gate()
        self.assertEqual(rig.store.get_node(step).state, State.WAITING)

        rig.use_case.execute(100)
        for tick in range(300):
            rig.use_case.execute(101 + tick)
            if rig.records(step)["a"]["status"] != "running":
                break
            time.sleep(0.02)

        record = rig.records(step)["a"]
        self.assertEqual(record["status"], "ok", record)
        self.assertEqual(record["artifacts"][0]["value"], "myapp://open?x=1")

    def test_a_real_script_usage_lands_on_the_gate_step(self):
        directory = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        script = os.path.join(directory, "callout.sh")
        with open(script, "w") as f:
            f.write(
                "#!/bin/sh\ncat >/dev/null\n"
                'echo \'{"status":"ok","usage":{"cost_usd":0.42,"model":"m"}}\'\n')
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        runner = ScriptRunnerAdapter(
            Config(environ={"LC_HOME": home, "LC_WORKER_HISTORY": "20"}), RunGroupsAdapter())
        real = callout("a", "pr")
        real = type(real)(
            id="a", command=script, subject="pr", principal_outputs=("code",), wait=False,
            timeout=30)
        rig = CalloutRig([real], runner=runner)
        step = rig.gate()

        rig.use_case.execute(100)
        for tick in range(300):
            rig.use_case.execute(101 + tick)
            if rig.records(step)["a"]["status"] != "running":
                break
            time.sleep(0.02)

        stored = rig.store.get_step(step)
        self.assertEqual(rig.records(step)["a"]["status"], "ok")
        self.assertEqual(stored.usage_cost_usd.to_usd(), 0.42)
        self.assertEqual(stored.usage_cost_basis, "reported")


class TestCleanupThroughTheRealRunner(unittest.TestCase):
    def test_a_real_script_answers_cleanup_by_writing_a_marker(self):
        directory = tempfile.mkdtemp()
        home = tempfile.mkdtemp()
        marker = os.path.join(directory, "marker")
        script = os.path.join(directory, "callout.sh")
        with open(script, "w") as f:
            f.write(
                "#!/bin/sh\ninput=$(cat)\ncase \"$input\" in *cleanup*) : > %s;; esac\n"
                'echo \'{"status":"ok"}\'\n' % marker)
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        runner = ScriptRunnerAdapter(
            Config(environ={"LC_HOME": home, "LC_WORKER_HISTORY": "20"}), RunGroupsAdapter())
        real = type(callout("a", "pr"))(
            id="a", command=script, subject="pr", principal_outputs=("code",), wait=False,
            timeout=30)
        rig = CalloutRig([real], runner=runner)
        step = rig.gate()
        rig.use_case.execute(100)
        for tick in range(300):
            rig.use_case.execute(101 + tick)
            if rig.records(step)["a"]["status"] not in ("running",) and not rig.runner.running():
                break
            time.sleep(0.02)
        self.assertEqual(rig.records(step)["a"]["status"], "ok")
        rig.store.complete_node(step, "approved")

        for _ in range(300):
            rig.use_case.execute(time.time())
            if os.path.exists(marker):
                break
            time.sleep(0.02)

        self.assertTrue(os.path.exists(marker), rig.records(step))
