import contextlib
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional

from lightcycle.adapters.workers import workers_state
from lightcycle.domain.pool.rate_limit import parse_rate_limit_event
from lightcycle.domain.pool.worker_session import CLOSE, NUDGE, SessionPolicy
from lightcycle.ports.workers import RegistryUnreadable


class SessionError(Exception):
    pass


@dataclass(frozen=True)
class SessionPlan:
    model: str
    sysprompt: str
    workspace: Optional[str] = None
    stage: Optional[str] = None


def plan_session(claim, resolve, reclaim, role):
    resp = claim(role)
    if resp is None:
        return None
    step_file = resp.step_file
    agent = resolve(step_file, resp.pin)
    if agent is None:
        reclaim(resp.view.step.id)
        raise SessionError("no step definition %r" % step_file)
    model = agent.meta.get("model")
    if not model:
        reclaim(resp.view.step.id)
        raise SessionError("step %r has no 'model' in frontmatter" % step_file)
    return SessionPlan(
        model=model, sysprompt=agent.body, workspace=resp.workspace, stage=resp.view.step.step
    )


def session_cwd(workspace):
    if workspace:
        return contextlib.nullcontext(workspace)
    return tempfile.TemporaryDirectory(prefix="lc-worker-")

MAX_LINE_BYTES = 1_000_000
KICKOFF = ("You are the %s step. Claim your next step and complete it per your step instructions, "
           "then exit.")
NUDGE_TEXT = ("Your previous turn ended but your step is not resolved yet. Continue and finish it, "
              "reach your terminal lc outcome, then exit.")
EXIT_GRACE_SECONDS = 20


def user_message(text):
    return json.dumps({"type": "user",
                       "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


COMMAND = "command"
RESULT = "result"
RATE_LIMIT = "rate-limit"


def dispatch_event(d, line, events):
    t = d.get("type")
    if t == "assistant":
        for c in d.get("message", {}).get("content", []):
            if c.get("type") == "tool_use":
                inp = c.get("input", {}) or {}
                events.put((COMMAND, str(inp.get("command", ""))))
    elif t == "result":
        events.put((RESULT, None))
    elif t == "rate_limit_event":
        events.put((RATE_LIMIT, parse_rate_limit_event([line])))


def has_open_step(root, spawnid):
    try:
        entries = workers_state(root)
    except RegistryUnreadable:
        return True
    for e in entries:
        if e.get("spawnid") == spawnid:
            return e.get("step") is not None
    return False


def build_command(model, sysprompt, root):
    return ["claude", "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--model", model,
            "--append-system-prompt", sysprompt,
            "--add-dir", root,
            "--dangerously-skip-permissions"]


def drain(events, policy):
    results = 0
    while True:
        try:
            kind, payload = events.get_nowait()
        except queue.Empty:
            return results
        if kind == COMMAND:
            policy.observe_command(payload)
        elif kind == RATE_LIMIT:
            policy.observe_rate_limit(payload)
        elif kind == RESULT:
            results += 1


def poll_decision(add_dir, spawnid, policy, events):
    if not drain(events, policy):
        return None
    open_step = has_open_step(add_dir, spawnid)
    policy.observe_claimed(open_step)
    return policy.on_result(open_step)


def run(add_dir, cwd, stage, spawnid, model, sysprompt, max_session_seconds, clock=time.monotonic):
    proc = subprocess.Popen(build_command(model, sysprompt, add_dir), cwd=cwd,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    policy = SessionPolicy()
    events = queue.Queue()

    def send(text):
        try:
            proc.stdin.write(user_message(text) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def reader():
        while True:
            raw = proc.stdout.readline(MAX_LINE_BYTES)
            if raw == "":
                break
            sys.stdout.write(raw)
            sys.stdout.flush()
            line = raw.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            dispatch_event(d, line, events)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    send(KICKOFF % stage)

    start = clock()
    while proc.poll() is None:
        if clock() - start > max_session_seconds:
            proc.terminate()
            break
        decision = poll_decision(add_dir, spawnid, policy, events)
        if decision == CLOSE:
            try:
                proc.stdin.close()
            except (BrokenPipeError, ValueError):
                pass
            break
        if decision == NUDGE:
            send(NUDGE_TEXT)
        time.sleep(1)

    deadline = clock() + EXIT_GRACE_SECONDS
    while proc.poll() is None and clock() < deadline:
        time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
        time.sleep(2)
        if proc.poll() is None:
            proc.kill()
    rc = proc.wait()
    reader_thread.join(timeout=5)
    return rc
