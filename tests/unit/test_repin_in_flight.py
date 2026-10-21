import unittest

from lightcycle.application.errors import UseCaseError
from lightcycle.application.workflows.pin_drift import PinDrift
from lightcycle.application.workflows.repin_in_flight import (
    RepinInFlightItemsUseCase,
    RepinResponse,
    RepinnedItem,
    HeldItem,
)
from lightcycle.cli import _repin_lines
from lightcycle.ports.workflow_bundle import StepPrompt
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

OLD_GRAPH = "entry: write\nedges:\n  write done review\n  review done ship\n"
NEW_GRAPH = "entry: write\nedges:\n  write done review\n  review done ship\n"


class _Config:
    def prompts_root(self):
        return "/prompts"


class _Source:
    def __init__(self, current="sha2"):
        self.current = current

    def current_sha(self, origin):
        return self.current if origin == "acme" else None

    def pinned_bundle(self, origin, sha):
        return (origin, sha)


class _Bundle:
    def __init__(self, bodies, texts):
        self.bodies = bodies
        self.texts = texts

    def step_roles(self, root):
        return sorted(self.bodies.get(root, {}))

    def parse_step(self, role, root):
        roots = root if isinstance(root, list) else [root]
        body = next((self.bodies[r][role] for r in roots if role in self.bodies.get(r, {})), None)
        found = next((r for r in roots if role in self.bodies.get(r, {})), None)
        meta = getattr(self, "metas", {}).get(found, {}).get(role, {"model": "sonnet"})
        return None if body is None else StepPrompt(meta=meta, body=body)

    def workflow_text(self, name, root):
        return self.texts.get((root, name))


class _Flow:
    def __init__(self, source, failing=()):
        self._source = source
        self._failing = set(failing)

    def resolve_selection(self, selector):
        origin, name = selector.split("/")
        return "%s/%s@%s" % (origin, name, self._source.current_sha(origin))

    def load_graph(self, pin):
        if pin in self._failing:
            raise ValueError("graph does not load")


def _drift(bodies, texts):
    return PinDrift(_Source(), _Bundle(bodies, texts), _Config())


OLD = ("acme", "sha1")
NEW = ("acme", "sha2")


class TestChangedStepsAhead(unittest.TestCase):
    def _bodies(self, **changed):
        old = {"write": "w", "review": "r", "ship": "s"}
        new = dict(old)
        new.update(changed)
        return {OLD: old, NEW: new}

    def _texts(self, new_graph=NEW_GRAPH, old_graph=OLD_GRAPH):
        return {(OLD, "build"): old_graph, (NEW, "build"): new_graph}

    def test_changed_step_ahead_is_reported(self):
        drift = _drift(self._bodies(review="r2"), self._texts())
        got = drift.changed_steps_ahead([("write", False)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, ["review"])

    def test_changed_step_behind_is_omitted(self):
        drift = _drift(self._bodies(write="w2"), self._texts())
        got = drift.changed_steps_ahead([("review", False)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, [])

    def test_running_step_does_not_count_its_own_changed_text(self):
        drift = _drift(self._bodies(review="r2"), self._texts())
        got = drift.changed_steps_ahead([("review", True)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, [])

    def test_step_added_only_in_the_new_graph_is_reported(self):
        bodies = self._bodies()
        bodies[NEW]["audit"] = "new"
        new_graph = "entry: write\nedges:\n  write done review\n  review done audit\n  audit done ship\n"
        drift = _drift(bodies, self._texts(new_graph=new_graph))
        got = drift.changed_steps_ahead([("write", False)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, ["audit"])

    def test_missing_workflow_text_falls_back_to_the_whole_changed_set(self):
        drift = _drift(self._bodies(write="w2"), {})
        got = drift.changed_steps_ahead([("ship", False)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, ["write"])

    def test_parse_error_falls_back_to_the_whole_changed_set(self):
        drift = _drift(self._bodies(write="w2"), self._texts(new_graph="edges:\n  write\n"))
        got = drift.changed_steps_ahead([("ship", False)], "acme", "build", "sha1", "sha2")
        self.assertEqual(got, ["write"])


class TestRepinInFlight(unittest.TestCase):
    def _store_with(self, items):
        store = FakeStore()
        ids = {}
        for key, (workflow, stage, state) in items.items():
            item = store.create_item(key, "d", workflow=workflow)
            store.update_state(item, "in_progress")
            if stage:
                step = store.create_step(stage=stage, role="agent", item=item)
                store.update_state(step, state)
            ids[key] = item
        return store, ids

    def setUp(self):
        self.fs = FakeFs()

    def _use_case(self, store, bodies, failing=(), metas=None):
        source = _Source()
        texts = {(OLD, "build"): OLD_GRAPH, (NEW, "build"): NEW_GRAPH}
        bundle = _Bundle(bodies, texts)
        bundle.metas = metas or {}
        drift = PinDrift(source, bundle, _Config())
        return RepinInFlightItemsUseCase(store, source, _Flow(source, failing), drift, _Config(), self.fs)

    BODIES = {
        OLD: {"write": "w", "review": "r", "ship": "s"},
        NEW: {"write": "w", "review": "r2", "ship": "s"},
    }

    def test_item_with_a_changed_step_ahead_is_repinned(self):
        store, ids = self._store_with({"a": ("acme/build@sha1", "write", "queued")})
        resp = self._use_case(store, self.BODIES).execute("acme")
        self.assertEqual(store.get_item(ids["a"]).workflow, "acme/build@sha2")
        self.assertEqual(resp.repinned, [RepinnedItem(ids["a"], "a", "acme/build@sha2", ["review"])])
        self.assertEqual(resp.left, 0)

    def test_item_with_nothing_changed_ahead_keeps_its_pin(self):
        store, ids = self._store_with({"a": ("acme/build@sha1", "ship", "queued")})
        resp = self._use_case(store, self.BODIES).execute("acme")
        self.assertEqual(store.get_item(ids["a"]).workflow, "acme/build@sha1")
        self.assertEqual((resp.repinned, resp.held, resp.left), ([], [], 1))

    def test_item_whose_open_step_is_not_in_the_new_graph_is_held(self):
        store, ids = self._store_with({"a": ("acme/build@sha1", "gone", "queued")})
        bodies = {OLD: {"write": "w", "gone": "g"}, NEW: {"write": "w", "gone": "g2"}}
        resp = self._use_case(store, bodies).execute("acme")
        self.assertEqual(store.get_item(ids["a"]).workflow, "acme/build@sha1")
        self.assertEqual([h.id for h in resp.held], [ids["a"]])
        self.assertEqual(resp.left, 1)

    def test_mixed_origin_lists_one_of_each_and_leaves_two(self):
        store, ids = self._store_with({
            "repin": ("acme/build@sha1", "write", "queued"),
            "unchanged": ("acme/build@sha1", "ship", "queued"),
            "held": ("acme/build@sha1", "gone", "queued"),
        })
        bodies = {
            OLD: {"write": "w", "review": "r", "ship": "s", "gone": "g"},
            NEW: {"write": "w", "review": "r2", "ship": "s", "gone": "g2"},
        }
        resp = self._use_case(store, bodies).execute("acme")
        self.assertEqual([r.id for r in resp.repinned], [ids["repin"]])
        self.assertEqual([h.id for h in resp.held], [ids["held"]])
        self.assertEqual(resp.left, 2)

    def test_other_origin_done_item_and_current_item_are_untouched(self):
        store, ids = self._store_with({
            "other": ("zed/build@sha1", "write", "queued"),
            "current": ("acme/build@sha2", "write", "queued"),
            "done": ("acme/build@sha1", "write", "queued"),
        })
        store.update_state(ids["done"], "done")
        resp = self._use_case(store, self.BODIES).execute("acme")
        self.assertEqual(store.get_item(ids["other"]).workflow, "zed/build@sha1")
        self.assertEqual(store.get_item(ids["current"]).workflow, "acme/build@sha2")
        self.assertEqual(store.get_item(ids["done"]).workflow, "acme/build@sha1")
        self.assertEqual((resp.repinned, resp.held, resp.left), ([], [], 0))

    def test_a_graph_that_does_not_load_holds_every_item(self):
        store, ids = self._store_with({
            "first": ("acme/build@sha1", "write", "queued"),
            "second": ("acme/build@sha1", "write", "queued"),
        })
        use_case = self._use_case(store, self.BODIES, failing=["acme/build@sha2"])
        resp = use_case.execute("acme")
        self.assertEqual(sorted(h.id for h in resp.held), sorted(ids.values()))
        self.assertEqual(resp.repinned, [])

    def test_a_failing_edit_holds_only_that_item(self):
        store, ids = self._store_with({
            "first": ("acme/build@sha1", "write", "queued"),
            "second": ("acme/build@sha1", "write", "queued"),
        })
        original = store.edit_node
        calls = []

        def flaky(tid, **kw):
            calls.append(tid)
            if len(calls) == 1:
                raise UseCaseError("boom")
            return original(tid, **kw)

        store.edit_node = flaky
        resp = self._use_case(store, self.BODIES).execute("acme")
        self.assertEqual(len(resp.held), 1)
        self.assertEqual(len(resp.repinned), 1)


class TestRepinReowns(unittest.TestCase):
    BODIES = {OLD: {"write": "w", "review": "r", "ship": "s"}, NEW: {"write": "w", "review": "r", "ship": "s"}}
    METAS = {NEW: {
        "write": {"model": "sonnet"}, "review": {"script": "scripts/review.py"}, "ship": {},
    }}

    def setUp(self):
        self.fs = FakeFs()
        self.store = FakeStore()
        self.item = self.store.create_item("a", "d", workflow="acme/build@sha1")
        self.store.update_state(self.item, "in_progress")

    def _step(self, stage, role, state="queued"):
        step = self.store.create_step(stage=stage, role=role, item=self.item)
        self.store.update_state(step, state)
        return step

    def _park(self, step, **fields):
        self.store._records[step].setdefault("metadata", {}).update(fields)

    def _run(self, metas=None):
        source = _Source()
        texts = {(OLD, "build"): OLD_GRAPH, (NEW, "build"): NEW_GRAPH}
        bundle = _Bundle(self.BODIES, texts)
        bundle.metas = metas if metas is not None else self.METAS
        drift = PinDrift(source, bundle, _Config())
        return RepinInFlightItemsUseCase(
            self.store, source, _Flow(source), drift, _Config(), self.fs).execute("acme")

    def test_open_agent_step_of_a_script_stage_becomes_an_engine_step_the_runner_claims(self):
        step = self._step("review", "agent")
        resp = self._run()
        self.assertEqual(self.store.get_node(step).role, "engine")
        self.assertEqual(resp.repinned[0].changed_steps, ["review"])
        self.assertEqual(self.store.claim_ready("agent"), None)
        self.assertEqual(self.store.claim_ready("engine", "runner").id, step)

    def test_owner_change_writes_one_run_log_line(self):
        self._step("review", "agent")
        self._run()
        log = self.fs._files["%s/run.log" % self.fs.ensure_logs_dir().rstrip("/")].decode()
        lines = [l for l in log.splitlines() if "repin" in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("agent -> engine", lines[0])

    def test_done_step_is_untouched(self):
        step = self._step("review", "agent", "done")
        self._step("ship", "agent")
        self._run()
        self.assertEqual(self.store.get_node(step).role, "agent")

    def test_parked_human_step_stays_parked(self):
        step = self._step("ship", "human", "waiting")
        self._park(step, needs="a decision")
        before = self.store.get_node(step)
        self._run()
        after = self.store.get_node(step)
        self.assertEqual((after.role, after.state, after.park), (before.role, before.state, before.park))

    def test_parked_agent_step_keeps_its_park_when_its_owner_changes(self):
        step = self._step("review", "agent", "waiting")
        self._park(step, reason="stuck", needs="a fix")
        before = self.store.get_node(step)
        self._run()
        after = self.store.get_node(step)
        self.assertEqual(after.role, "engine")
        self.assertEqual((after.state, after.park), (before.state, before.park))

    def test_failing_reassign_on_the_second_step_leaves_the_pin_and_first_step_unchanged(self):
        first = self._step("review", "agent")
        second = self._step("write", "human")
        real = self.store.reassign

        def flaky(tid, role):
            if tid == second:
                raise RuntimeError("boom")
            real(tid, role)

        self.store.reassign = flaky
        with self.assertRaises(RuntimeError):
            self._run()
        self.assertEqual(self.store.get_node(first).role, "agent")
        self.assertEqual(self.store.get_node(second).role, "human")
        self.assertEqual(self.store.get_item(self.item).workflow, "acme/build@sha1")
        self.assertEqual(self.fs._files, {})

    def test_stage_missing_from_the_new_graph_refuses_the_repin_naming_it(self):
        step = self._step("gone", "agent")
        resp = self._run()
        self.assertEqual(resp.repinned, [])
        self.assertIn("'gone'", resp.held[0].reason)
        self.assertEqual(self.store.get_node(step).role, "agent")
        self.assertEqual(self.store.get_item(self.item).workflow, "acme/build@sha1")


class TestRepinLines(unittest.TestCase):
    def test_moved_origin_prints_repinned_held_and_left_lines(self):
        resp = RepinResponse(
            repinned=[RepinnedItem("LC-12", "Some title", "acme/build@abc", ["review-code", "write-code"])],
            held=[HeldItem("LC-14", "open step 'x' is not in the new graph")],
            left=3)
        self.assertEqual(_repin_lines(resp), [
            'repinned LC-12 "Some title" -> acme/build@abc: changed steps ahead: review-code, write-code',
            "held LC-14: open step 'x' is not in the new graph",
            "left 3 in-flight item(s) on their pin (nothing changed ahead, or held)",
        ])

    def test_no_repin_response_prints_nothing(self):
        self.assertEqual(_repin_lines(None), [])
