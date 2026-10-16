import json
import os
import stat

from lightcycle.domain.workflows.contract import ENGINE_CONTRACT

WORKFLOW = """entry: poll

requires: repo

edges:
  poll  found  finish
  poll  none   idle

display:
  finish  Finished
  idle    Idle
"""

STAGE_FIXTURE = {
    "found": {"outcome": "found", "artifacts": {"digest": "3 new rows"}, "note": "rows found"},
    "none": {"outcome": "none"},
}

GUARD_FIXTURE = {
    "pass": {"outcome": "pass", "title": "Sheet changed", "description": "d", "state": "c1"},
    "fail": {"outcome": "fail"},
}

POLL_SH = """#!/bin/sh
cat > /dev/null
echo '{"outcome": "found", "artifacts": {"digest": "3 new rows"}, "note": "rows found"}'
"""

CHANGED_SH = """#!/bin/sh
cat > /dev/null
echo '{"outcome": "pass", "title": "Sheet changed", "description": "d", "state": "c1"}'
"""


def _write(path, text, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_script_bundle(
        root, *, requires_engine=True, stage_script="scripts/poll.sh", guard=True,
        stage_fixture=STAGE_FIXTURE, guard_fixture=GUARD_FIXTURE, poll_sh=POLL_SH,
        changed_sh=CHANGED_SH, poll_executable=True, step_extra="", config_block=False):
    manifest = 'name = "acme"\ncontract = %d\n' % ENGINE_CONTRACT
    if requires_engine:
        manifest += 'requires-engine = ">=0.6.0"\n'
    _write(os.path.join(root, "source.toml"), manifest)
    front = ["---"]
    if stage_script:
        front.append("script: %s" % stage_script)
    if step_extra:
        front.append(step_extra.rstrip("\n"))
    front.append("---")
    _write(os.path.join(root, "steps", "poll.md"), "\n".join(front) + "\nPoll the sheet.\n")
    _write(os.path.join(root, "steps", "finish.md"), "Finish, terminal.\n")
    _write(os.path.join(root, "steps", "idle.md"), "Idle, terminal.\n")
    meta = []
    if guard:
        meta.append("schedule:\n  cron: 0 * * * *\n  guard: script:scripts/changed.sh")
    if config_block:
        meta.append("config:\n  api-token: required\nconfig-example:\n  api-token: example")
    text = WORKFLOW
    if meta:
        text = "---\n" + "\n".join(meta) + "\n---\n" + text
    _write(os.path.join(root, "workflows", "build.md"), text)
    if poll_sh is not None:
        _write(os.path.join(root, "scripts", "poll.sh"), poll_sh, executable=poll_executable)
    if guard and changed_sh is not None:
        _write(os.path.join(root, "scripts", "changed.sh"), changed_sh, executable=True)
    if stage_fixture is not None:
        _write(os.path.join(root, "scripts", "fixtures", "poll.sh.json"), json.dumps(stage_fixture))
    if guard and guard_fixture is not None:
        _write(
            os.path.join(root, "scripts", "fixtures", "changed.sh.json"),
            json.dumps(guard_fixture))
    return root
