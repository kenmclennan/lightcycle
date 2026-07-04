import json
import os
import subprocess
import sys
import threading
import time

from the_grid.adapters import fsio
from the_grid.adapters.workers import workers_state
from the_grid.domain.pool.worker_session import CLOSE, NUDGE, SessionPolicy

KICKOFF = ("You are the %s. Claim your next task and complete it per your role instructions, "
           "then exit.")
NUDGE_TEXT = ("Your previous turn ended but your task is not resolved yet. Continue and finish it, "
              "reach your terminal tg outcome, then exit.")
MAX_SESSION_SECONDS = 1800
EXIT_GRACE_SECONDS = 20


def user_message(text):
    return json.dumps({"type": "user",
                       "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def has_open_task(root, spawnid):
    for e in workers_state(root):
        if e.get("spawnid") == spawnid:
            return e.get("task") is not None
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


def run(root, role, spawnid, model, sysprompt):
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

    threading.Thread(target=reader, daemon=True).start()
    send(KICKOFF % role)

    start = time.time()
    processed = 0
    while proc.poll() is None:
        if time.time() - start > MAX_SESSION_SECONDS:
            proc.terminate()
            break
        with lock:
            pending = counters["results"] > processed
            processed = counters["results"]
        if pending:
            open_task = has_open_task(root, spawnid)
            policy.observe_claimed(open_task)
            decision = policy.on_result(open_task)
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
    return proc.wait()


def main():
    root = os.environ.get("GRID_ROOT_OVERRIDE")
    role = os.environ.get("GRID_ROLE")
    spawnid = os.environ.get("GRID_SPAWNID")
    if not (root and role and spawnid):
        sys.stderr.write("worker_session: GRID_ROOT_OVERRIDE, GRID_ROLE, GRID_SPAWNID required\n")
        return 1
    agent = fsio.parse_step(root, role)
    if agent is None:
        sys.stderr.write("worker_session: no agent definition for role %s\n" % role)
        return 1
    model = agent["meta"].get("model")
    if not model:
        sys.stderr.write("worker_session: agent %s has no 'model' in frontmatter\n" % role)
        return 1
    return run(root, role, spawnid, model, agent["body"])


if __name__ == "__main__":
    sys.exit(main())
