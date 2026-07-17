import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from lightcycle.adapters.workers import workers_state
from lightcycle.adapters.workflow_source import resolve_agent_for_pin
from lightcycle.application.flow.claim_step import ClaimInput, ClaimStepUseCase
from lightcycle.container import Container
from lightcycle.domain.pool.worker_session import CLOSE, NUDGE, SessionPolicy


class SessionError(Exception):
    pass


@dataclass(frozen=True)
class SessionPlan:
    model: str
    sysprompt: str


def plan_session(claim, resolve, reclaim, role):
    resp = claim(role)
    if resp is None:
        return None
    agent = resolve(role, resp.pin)
    if agent is None:
        reclaim(resp.view.step.id)
        raise SessionError("no agent definition for role %s" % role)
    model = agent["meta"].get("model")
    if not model:
        reclaim(resp.view.step.id)
        raise SessionError("agent %s has no 'model' in frontmatter" % role)
    return SessionPlan(model=model, sysprompt=agent["body"])

KICKOFF = ("You are the %s. Claim your next step and complete it per your role instructions, "
           "then exit.")
NUDGE_TEXT = ("Your previous turn ended but your step is not resolved yet. Continue and finish it, "
              "reach your terminal lc outcome, then exit.")
EXIT_GRACE_SECONDS = 20


def user_message(text):
    return json.dumps({"type": "user",
                       "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def has_open_step(root, spawnid):
    for e in workers_state(root):
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


def run(root, role, spawnid, model, sysprompt, max_session_seconds):
    proc = subprocess.Popen(build_command(model, sysprompt, root), cwd=root,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    policy = SessionPolicy()
    counters = {"results": 0}
    lock = threading.Lock()

    def send(text):
        try:
            proc.stdin.write(user_message(text) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def reader():
        for raw in proc.stdout:
            sys.stdout.write(raw)
            sys.stdout.flush()
            line = raw.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            if t == "assistant":
                for c in d.get("message", {}).get("content", []):
                    if c.get("type") == "tool_use":
                        inp = c.get("input", {}) or {}
                        policy.observe_command(str(inp.get("command", "")))
            elif t == "result":
                with lock:
                    counters["results"] += 1

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    send(KICKOFF % role)

    start = time.time()
    processed = 0
    while proc.poll() is None:
        if time.time() - start > max_session_seconds:
            proc.terminate()
            break
        with lock:
            pending = counters["results"] > processed
            processed = counters["results"]
        if pending:
            open_step = has_open_step(root, spawnid)
            policy.observe_claimed(open_step)
            decision = policy.on_result(open_step)
            if decision == CLOSE:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, ValueError):
                    pass
                break
            if decision == NUDGE:
                send(NUDGE_TEXT)
        time.sleep(1)

    deadline = time.time() + EXIT_GRACE_SECONDS
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.5)
    if proc.poll() is None:
        proc.terminate()
        time.sleep(2)
        if proc.poll() is None:
            proc.kill()
    rc = proc.wait()
    reader_thread.join(timeout=5)
    return rc


def main():
    role = os.environ.get("LC_ROLE")
    spawnid = os.environ.get("LC_SPAWNID")
    if not (role and spawnid):
        sys.stderr.write("worker_session: LC_ROLE, LC_SPAWNID required\n")
        return 1
    container = Container()
    config = container.config
    claim = ClaimStepUseCase(
        container.store, container.flow_service(), container.worktrees(),
        container.workers, config,
    )
    try:
        plan = plan_session(
            lambda r: claim.execute(ClaimInput(role=r)),
            lambda r, pin: resolve_agent_for_pin(config, r, pin),
            container.store.reclaim,
            role,
        )
    except Exception as e:
        sys.stderr.write("worker_session: %s\n" % e)
        return 1
    if plan is None:
        return 0
    return run(config.data_root(), role, spawnid, plan.model, plan.sysprompt,
               config.max_session_seconds())


if __name__ == "__main__":
    _rc = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (ValueError, OSError):
        pass
    os._exit(_rc if isinstance(_rc, int) else 0)
