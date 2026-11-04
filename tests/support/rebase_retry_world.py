import datetime

from tests.support.harness import DEFAULT_WORKFLOW, Harness

GRAPH = (
    "entry: write\n\n"
    "nodes:\n"
    "  write    coder\n"
    "  ci       poller\n"
    "  recheck  watcher\n"
    "  gate     gate\n\n"
    "phase:\n"
    "  write    code\n"
    "  ci       code\n"
    "  recheck  code\n"
    "  gate     code\n\n"
    "edges:\n"
    "  write    done       ci\n"
    "  ci       succeeded  gate\n"
    "  ci       failed     recheck\n"
    "  recheck  retried    ci\n"
    "  recheck  broke      write\n"
    "  recheck  done       gate\n"
    "  gate     merged\n\n"
    "hooks:\n"
    "  ci_success     ci       succeeded\n"
    "  ci_failure     ci       failed\n"
    "  ci_failed_cap  recheck  %s  3  write\n"
    "  pr_merge       gate     merged\n"
)

STEPS = {
    "coder": "---\nmodel: sonnet\n---\n# coder\nstub\n",
    "poller": "---\nengine: true\n---\n# poller\nstub\n",
    "watcher": "---\nmodel: sonnet\n---\n# watcher\nstub\n",
    "gate": "# gate\nstub\n",
}


def graph_text(failure_outcome="broke", with_cap=True):
    text = GRAPH % failure_outcome
    if not with_cap:
        text = "".join(l for l in text.splitlines(True) if "ci_failed_cap" not in l)
    return text


class RebaseWorld:
    def __init__(self, failure_outcome="broke", with_cap=True):
        self.h = Harness(
            [], workflow_text=graph_text(failure_outcome, with_cap), extra_steps=dict(STEPS))
        self.store = self.h.store
        self._tick = 0
        self.base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        self.store._now = self._now
        self.item = self.store.create_item("a thing", "a description", workflow=DEFAULT_WORKFLOW)
        rc, _out, err = self.h.run("set", self.item, "--state", "active", "--step", "write")
        assert rc == 0, err
        (opening,) = [c for c in self.store.children(self.item) if c.stage == "write"]
        rc, _out, err = self.h.run("done", opening.id, "done")
        assert rc == 0, err
        self.pass_id = self.store.current_pass(self.item).id
        self.run = self.store.open_run(self.item, self.pass_id, "code")

    def _now(self):
        self._tick += 1
        return (self.base + datetime.timedelta(seconds=self._tick)).isoformat()

    def new_round(self):
        self.store.close_run(self.run)
        self.run = self.store.open_run(self.item, self.pass_id, "code")

    def recheck(self):
        return self.store.create_step(stage="recheck", role="agent", item=self.item)

    def close(self, step, outcome, note=None):
        args = ["done", step, outcome]
        if note is not None:
            args += ["--note", note]
        return self.h.run(*args)

    def retry(self, note):
        step = self.recheck()
        rc, _out, err = self.close(step, "retried", note)
        return step, rc, err

    def claim_next(self):
        rc, out, err = self.h.run_as_worker("w1", "claim", "agent")
        assert rc == 0, err
        return out
