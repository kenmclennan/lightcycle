import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from lightcycle.adapters.workflow_bundle import parse_step
from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow import CompleteInput, CompleteStepUseCase
from lightcycle.application.flow.engine_steps import (
    FINDINGS_STEP, MATERIAL_AUDIT_STEP, RETRO_ORIGIN_LABEL,
)
from lightcycle.application.pool.material_audit_cadence import (
    MaterialAuditCadenceResponse, MaterialAuditCadenceUseCase,
)
from lightcycle.application.pool.no_op_gates import NoOpMaterialAuditGate
from lightcycle.application.pool.retro_cadence import RetroCadenceUseCase
from lightcycle.cli import _format_tick
from lightcycle.config import Config
from lightcycle.domain.work import State, parse_timestamp
from lightcycle.domain.work.worker_permissions import worker_permitted
from tests.support.fake_store import FakeStore
from tests.unit.test_flow_usecases import METAS, FakeWorktrees, flow_for
from tests.unit.test_format_tick import _NOW, _result

_DAY = 86400


class FakeConfig:
    def __init__(self, days=7, audit_shortcode="AUD", interval_reflections=1):
        self._days = days
        self._audit_shortcode = audit_shortcode
        self._interval = interval_reflections

    def material_audit_days(self):
        return self._days

    def audit_shortcode(self):
        return self._audit_shortcode

    def retro_interval_reflections(self):
        return self._interval


def _gate(store, days=7):
    return MaterialAuditCadenceUseCase(store, FakeConfig(days))


def _seed_audit(store, state=State.DONE):
    item = store.create_item("prior audit", "d", shortcode="AUD")
    step = store.create_step(step=MATERIAL_AUDIT_STEP, role="agent", parent=item)
    if state == State.DONE:
        store.complete_node(step, "done")
    return step


def _created(store, step):
    return parse_timestamp(store.get_node(step).created_at).timestamp()


class TestMaterialAuditCadenceTrigger(unittest.TestCase):
    def test_no_prior_audit_fires(self):
        s = FakeStore()
        result = _gate(s).execute(0.0)
        self.assertEqual(len(result.fired), 1)

    def test_open_audit_blocks(self):
        s = FakeStore()
        _seed_audit(s, state=State.WAITING)
        self.assertEqual(_gate(s).execute(1e12).fired, [])

    def test_one_second_short_of_the_window_does_not_fire(self):
        s = FakeStore()
        prior = _seed_audit(s)
        now = _created(s, prior) + 7 * _DAY - 1
        self.assertEqual(_gate(s).execute(now).fired, [])

    def test_exactly_the_window_fires(self):
        s = FakeStore()
        prior = _seed_audit(s)
        now = _created(s, prior) + 7 * _DAY
        self.assertEqual(len(_gate(s).execute(now).fired), 1)

    def test_abandoned_prior_audit_still_counts_as_fired(self):
        s = FakeStore()
        prior = _seed_audit(s)
        s.complete_node(prior, "abandoned")
        now = _created(s, prior) + 7 * _DAY - 1
        self.assertEqual(_gate(s).execute(now).fired, [])

    def test_days_come_from_config(self):
        s = FakeStore()
        prior = _seed_audit(s)
        now = _created(s, prior) + 2 * _DAY
        self.assertEqual(_gate(s, days=3).execute(now).fired, [])
        self.assertEqual(len(_gate(s, days=2).execute(now).fired), 1)


class TestMaterialAuditCadenceFiredItem(unittest.TestCase):
    def test_first_audit_item_shape(self):
        s = FakeStore()
        sid = _gate(s).execute(0.0).fired[0]
        step = s.get_node(sid)
        item = s.get_node(step.item)
        self.assertEqual(step.stage, MATERIAL_AUDIT_STEP)
        self.assertEqual(step.role, "agent")
        self.assertIn(RETRO_ORIGIN_LABEL, s.labels_of(item.id))
        self.assertTrue(item.id.startswith("AUD"))
        self.assertEqual(item.title, "Audit of guidance and workflow bundles")
        self.assertEqual(item.description, "materials: guidance, workflows\nsince: none\nprevious: none")

    def test_later_audit_names_the_previous_one(self):
        s = FakeStore()
        prior = _seed_audit(s)
        now = _created(s, prior) + 7 * _DAY
        sid = _gate(s).execute(now).fired[0]
        since = parse_timestamp(s.get_node(prior).created_at).date().isoformat()
        self.assertEqual(
            s.get_node(s.get_node(sid).item).description,
            "materials: guidance, workflows\nsince: %s\nprevious: %s" % (since, prior),
        )

    def test_item_and_step_are_created_atomically(self):
        s = FakeStore()
        before = {i.id for i in s.all_items()}

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        s.create_step = boom
        with self.assertRaises(RuntimeError):
            _gate(s).execute(0.0)
        self.assertEqual({i.id for i in s.all_items()}, before)


class TestMaterialAuditIndependence(unittest.TestCase):
    def test_open_retro_audit_does_not_block_the_material_audit(self):
        s = FakeStore()
        item = s.create_item("retro", "d", shortcode="AUD")
        s.create_step(step="audit", role="agent", parent=item)
        self.assertEqual(len(_gate(s).execute(0.0).fired), 1)

    def test_open_material_audit_does_not_block_the_retro_audit(self):
        s = FakeStore()
        _seed_audit(s, state=State.WAITING)
        for i in range(2):
            eid = s.create_item("closed %d" % i, "d", shortcode="GRID")
            s.complete_node(eid, "done")
            k = s.create_step(step="build", role="agent", parent=eid)
            s.complete_node(k, "done")
            s.add_artifact(k, "reflection", "fb")
        fired = RetroCadenceUseCase(s, FakeConfig(interval_reflections=2)).execute(0.0).fired
        self.assertEqual(len(fired), 1)


class TestMaterialAuditCompletion(unittest.TestCase):
    def _uc(self, store):
        return CompleteStepUseCase(store, flow_for(METAS, store), FakeWorktrees())

    def _fired(self, store):
        return _gate(store).execute(0.0).fired[0]

    def _reviewed_item(self, store):
        item = store.create_item("reviewed", "d", shortcode="GRID")
        store.complete_node(item, "done")
        k = store.create_step(step="build", role="agent", parent=item)
        store.complete_node(k, "done")
        store.add_artifact(k, "reflection", "fb")
        return item

    def test_findings_creates_the_human_gate_and_marks_nothing_retroed(self):
        s = FakeStore()
        reviewed = self._reviewed_item(s)
        sid = self._fired(s)
        self._uc(s).execute(CompleteInput(step=sid, outcome="findings", note="the digest"))
        children = s.children(s.get_node(sid).item)
        human = [c for c in children if c.role == "human"]
        self.assertEqual(len(human), 1)
        self.assertEqual(human[0].stage, FINDINGS_STEP)
        notes = s.get_node(human[0].id).notes or ""
        self.assertTrue(notes.startswith("findings: lc show %s\n" % sid))
        self.assertIn("the digest", notes)
        self.assertIn(reviewed, [i.id for i in s.closed_unretroed_items()])

    def test_clean_closes_with_no_gate(self):
        s = FakeStore()
        sid = self._fired(s)
        self._uc(s).execute(CompleteInput(step=sid, outcome="clean"))
        item = s.get_node(sid).item
        self.assertEqual([c for c in s.children(item) if c.role == "human"], [])
        self.assertEqual(s.get_node(item).state, "done")

    def test_outcome_outside_the_table_is_refused_naming_the_valid_ones(self):
        s = FakeStore()
        sid = self._fired(s)
        with self.assertRaises(UseCaseError) as ctx:
            self._uc(s).execute(CompleteInput(step=sid, outcome="bogus"))
        self.assertIn("findings", str(ctx.exception))
        self.assertIn("clean", str(ctx.exception))

    def test_closed_audit_item_is_not_in_the_retro_batch(self):
        s = FakeStore()
        sid = self._fired(s)
        item = s.get_node(sid).item
        self._uc(s).execute(CompleteInput(step=sid, outcome="clean"))
        self.assertNotIn(item, [i.id for i in s.closed_unretroed_items()])


class TestMaterialAuditConfig(unittest.TestCase):
    def _cfg(self, environ=None, **filevals):
        env = dict(environ or {})
        if filevals:
            p = os.path.join(tempfile.mkdtemp(), "config")
            Path(p).write_text(
                "".join("%s: %s\n" % (k.replace("_", "-"), v) for k, v in filevals.items()))
            env["LC_CONFIG"] = p
        else:
            env.setdefault("LC_CONFIG", os.path.join(tempfile.mkdtemp(), "absent"))
        return Config(environ=env)

    def test_absent_key_raises(self):
        with self.assertRaises(Exception):
            self._cfg().material_audit_days()

    def test_accepts_seven(self):
        self.assertEqual(self._cfg(material_audit_days="7").material_audit_days(), 7)

    def test_rejects_zero_and_non_numeric(self):
        for bad in ("0", "lots"):
            with self.assertRaises(Exception):
                self._cfg(material_audit_days=bad).material_audit_days()

    def test_env_override_wins(self):
        cfg = self._cfg({"LC_MATERIAL_AUDIT_DAYS": "3"}, material_audit_days="7")
        self.assertEqual(cfg.material_audit_days(), 3)


class TestMaterialAuditTickWiring(unittest.TestCase):
    def test_no_op_gate_fires_nothing(self):
        self.assertEqual(NoOpMaterialAuditGate().execute(now=1.0), MaterialAuditCadenceResponse())

    def test_format_tick_prints_a_material_audit_line(self):
        result = replace(_result(), material_audit=MaterialAuditCadenceResponse(fired=["AUD-9.1"]))
        lines, _ = _format_tick(result, None, _NOW)
        self.assertTrue(any("material-audit" in l and "AUD-9.1" in l for l in lines))


class TestMaterialAuditWorkerVerbs(unittest.TestCase):
    def test_guidance_verbs_are_permitted_to_workers(self):
        self.assertTrue(worker_permitted("guidance", {}))
        self.assertTrue(worker_permitted("guidance-dir", {}))


class TestMaterialAuditPrompt(unittest.TestCase):
    _ROOT = str(Path(__file__).resolve().parents[2] / "lightcycle" / "prompts")

    def test_real_prompt_parses_with_includes_expanded(self):
        prompt = parse_step([self._ROOT], "material-audit")
        meta, body = prompt.meta, prompt.body
        self.assertEqual(meta, {"model": "sonnet"})
        self.assertNotIn("@include", body)

    def test_real_prompt_carries_every_verdict_word(self):
        body = parse_step([self._ROOT], "material-audit").body
        for word in ("rewrite", "rescope", "retire", "promote", "restore", "keep"):
            self.assertIn(word, body)
