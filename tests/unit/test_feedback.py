import datetime
import json
import unittest

from lightcycle.application.feedback import (
    ReflectInput,
    ReflectUseCase,
    RetroInput,
    RetroUseCase,
    WorklogInput,
    WorklogUseCase,
)
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.pending_reflections import pending_reflection_count
from lightcycle.domain.feedback import UNLABELED_MODEL
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

_METAS = {"reviewer": {"model": "opus", "step": "review", "signals": {"review_rounds": "rejected"}}}


def _flow(store):
    return FlowService(FakeFs(_METAS), store)


def _add_reflection(store, node_id, feedback):
    store.add_artifact(
        node_id, "reflection", json.dumps({"step": node_id, "feedback": feedback, "spec_hash": "h"})
    )


class TestReflect(unittest.TestCase):
    def test_records_reflection_on_the_task_with_spec_hash(self):
        s = FakeStore()
        item = s.create_item("st", theme=s.create_theme("theme"))
        s.add_artifact(item, "spec", "/specs/x.md")
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        fs = FakeFs(files={"/specs/x.md": b"spec body"})
        resp = ReflectUseCase(s, fs).execute(ReflectInput(step=k, feedback="went well"))
        self.assertEqual(resp.reflection.step, k)
        refl = json.loads(s.item_artifacts(k)[0].value)
        self.assertEqual(refl["step"], k)
        self.assertEqual(refl["feedback"], "went well")
        self.assertNotEqual(refl["spec_hash"], "unknown")

    def test_unknown_spec_hash_when_no_spec(self):
        s = FakeStore()
        k = s.create_step("loose step", role="human")
        ReflectUseCase(s, FakeFs()).execute(ReflectInput(step=k, feedback="fb"))
        refl = json.loads(s.item_artifacts(k)[0].value)
        self.assertEqual(refl["spec_hash"], "unknown")


class TestRetroEpicScope(unittest.TestCase):
    def test_gathers_feedback_and_signals(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        item = s.create_item("st", theme=theme)
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        _add_reflection(s, k, "fb1")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=theme))
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.feedback[0].text, "fb1")
        self.assertEqual(len(resp.item_signals), 1)
        self.assertEqual(resp.item_signals[0].reflections, 1)

    def test_empty_when_no_reflections(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        s.create_item("st", theme=theme)
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=theme))
        self.assertEqual(resp.reflection_count, 0)
        self.assertEqual(resp.feedback, [])

    def test_subject_label_is_the_epic_id(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        s.create_item("st", theme=theme)
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=theme))
        self.assertEqual(resp.subject, theme)


class TestRetroItemScope(unittest.TestCase):
    def test_story_scope_returns_single_row(self):
        s = FakeStore()
        item = s.create_item("standalone item", theme=s.create_theme("theme"))
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        _add_reflection(s, k, "item feedback")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=item))
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.feedback[0].text, "item feedback")
        self.assertEqual(len(resp.item_signals), 1)
        self.assertEqual(resp.item_signals[0].item.id, item)
        self.assertEqual(resp.item_signals[0].reflections, 1)

    def test_story_scope_with_no_tasks(self):
        s = FakeStore()
        item = s.create_item("empty item", theme=s.create_theme("theme"))
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=item))
        self.assertEqual(resp.reflection_count, 0)
        self.assertEqual(len(resp.item_signals), 1)
        self.assertEqual(resp.item_signals[0].item.id, item)

    def test_story_with_rejected_task_tallies_signal(self):
        s = FakeStore()
        item = s.create_item("item", theme=s.create_theme("theme"), workflow="standard")
        k = s.create_step("review: x", step="review", role="reviewer", parent=item)
        s.close(k, "rejected")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(subject=item))
        self.assertEqual(resp.item_signals[0].signals.get("review_rounds"), {UNLABELED_MODEL: 1})

    def test_each_item_is_tallied_with_its_own_workflow_signals(self):
        s = FakeStore()
        wf_a = "entry: review\n\nedges:\n  review  rejected  review\n\nsignals:\n  review  rounds_a  rejected\n"
        wf_b = "entry: review\n\nedges:\n  review  rejected  review\n\nsignals:\n  review  rounds_b  rejected\n"
        flow = FlowService(FakeFs(_METAS, workflow={"wf-a": wf_a, "wf-b": wf_b}), s)
        theme = s.create_theme("theme")
        a = s.create_item("a", theme=theme, workflow="wf-a")
        b = s.create_item("b", theme=theme, workflow="wf-b")
        s.close(s.create_step("review: a", step="review", role="reviewer", parent=a), "rejected")
        s.close(s.create_step("review: b", step="review", role="reviewer", parent=b), "rejected")

        rows = {r.item.id: r.signals for r in RetroUseCase(s, flow).execute(RetroInput(subject=theme)).item_signals}

        self.assertIn("rounds_a", rows[a])
        self.assertNotIn("rounds_b", rows[a])
        self.assertIn("rounds_b", rows[b])
        self.assertNotIn("rounds_a", rows[b])

    def test_an_unresolvable_item_workflow_yields_empty_signals_not_a_raise(self):
        s = FakeStore()
        flow = FlowService(FakeFs(_METAS, workflow={"wf-a": "entry: review\n"}), s)
        theme = s.create_theme("theme")
        item = s.create_item("gone", theme=theme, workflow="pruned-workflow")
        s.close(s.create_step("review: x", step="review", role="reviewer", parent=item), "rejected")

        resp = RetroUseCase(s, flow).execute(RetroInput(subject=theme))

        self.assertEqual(resp.item_signals[0].signals, {})


class TestRetroSinceScope(unittest.TestCase):
    def test_since_aggregates_closed_tasks_across_stories(self):
        s = FakeStore()
        theme = s.create_theme("theme")
        story1 = s.create_item("story1", theme=theme)
        k1 = s.create_step("build: a", step="build", role="coder", parent=story1)
        s.close(k1, "done")
        _add_reflection(s, k1, "reflection from story1")

        story2 = s.create_item("story2", theme=theme)
        k2 = s.create_step("build: b", step="build", role="coder", parent=story2)
        s.close(k2, "done")
        _add_reflection(s, k2, "reflection from story2")

        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 2)
        self.assertEqual(len(resp.item_signals), 2)
        story_ids = {row.item.id for row in resp.item_signals}
        self.assertIn(story1, story_ids)
        self.assertIn(story2, story_ids)

    def test_since_excludes_open_tasks(self):
        s = FakeStore()
        item = s.create_item("item", theme=s.create_theme("theme"))
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        _add_reflection(s, k, "not closed yet")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 0)

    def test_since_label_in_response(self):
        s = FakeStore()
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2024-06-01"))
        self.assertEqual(resp.subject, "since:2024-06-01")

    def test_since_includes_epicless_story_task(self):
        s = FakeStore()
        item = s.create_item("epicless item", theme=s.create_theme("theme"))
        s._records[item]["parent"] = None
        k = s.create_step("build: x", role="coder", parent=item)
        s.close(k, "done")
        _add_reflection(s, k, "epicless fb")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(since="2020-01-01"))
        self.assertEqual(resp.reflection_count, 1)


class TestRetroProjectScope(unittest.TestCase):
    def _closed_item(self, s, title, project, text):
        item = s.create_item(title, theme=s.create_theme("theme"))
        s.close(item, "merged")
        if project is not None:
            s.add_artifact(item, "repo", project)
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        s.close(k, "done")
        _add_reflection(s, k, text)
        return item

    def test_project_scope_gathers_only_that_project(self):
        s = FakeStore()
        saga = self._closed_item(s, "saga work", "saga", "saga friction")
        self._closed_item(s, "lc work", None, "lc friction")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(project="saga"))
        self.assertEqual({row.item.id for row in resp.item_signals}, {saga})
        self.assertEqual(resp.reflection_count, 1)
        self.assertEqual(resp.subject, "project:saga")

    def test_project_scope_excludes_retroed_items(self):
        s = FakeStore()
        item = self._closed_item(s, "saga work", "saga", "friction")
        s.label_add(item, "retroed")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(project="saga"))
        self.assertEqual(resp.item_signals, [])


class TestRetroPendingScope(unittest.TestCase):
    def _closed_item(self, s, title, project, text):
        item = s.create_item(title, theme=s.create_theme("theme"))
        s.close(item, "merged")
        if project is not None:
            s.add_artifact(item, "repo", project)
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        s.close(k, "done")
        _add_reflection(s, k, text)
        return item

    def test_pending_scope_gathers_feedback_across_projects_and_projectless_items(self):
        s = FakeStore()
        saga = self._closed_item(s, "saga work", "saga", "saga friction")
        lc = self._closed_item(s, "lc work", "lightcycle", "lc friction")
        orphan = self._closed_item(s, "orphan work", None, "orphan friction")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual({row.item.id for row in resp.item_signals}, {saga, lc, orphan})
        self.assertEqual(resp.reflection_count, 3)
        self.assertEqual(resp.subject, "pending")

    def test_pending_scope_excludes_feedback_less_items(self):
        s = FakeStore()
        item = s.create_item("no feedback", theme=s.create_theme("theme"))
        s.close(item, "done")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(resp.item_signals, [])

    def test_pending_scope_excludes_retroed_items(self):
        s = FakeStore()
        item = self._closed_item(s, "saga work", "saga", "friction")
        s.label_add(item, "retroed")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(resp.item_signals, [])

    def test_pending_scope_reflection_count_matches_shared_helper(self):
        s = FakeStore()
        self._closed_item(s, "saga work", "saga", "saga friction")
        self._closed_item(s, "lc work", "lightcycle", "lc friction")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(resp.reflection_count, pending_reflection_count(s))

    def test_pending_scope_counts_per_reflection_not_per_item(self):
        s = FakeStore()
        item = s.create_item("saga work", theme=s.create_theme("theme"))
        s.close(item, "merged")
        s.add_artifact(item, "repo", "saga")
        k = s.create_step("build: x", step="build", role="coder", parent=item)
        s.close(k, "done")
        _add_reflection(s, k, "first friction")
        _add_reflection(s, k, "second friction")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(pending=True))
        self.assertEqual(resp.reflection_count, 2)
        self.assertEqual(len(resp.item_signals), 1)


class TestRetroLastScope(unittest.TestCase):
    def _make_closed_epic(self, s, title):
        theme = s.create_theme(title)
        item = s.create_item("child of %s" % title, theme=theme)
        k = s.create_step("step", role="coder", parent=item)
        _add_reflection(s, k, "fb from %s" % title)
        s.close(theme, "merged")
        return theme

    def test_last_n_aggregates_exactly_n_closed_epics(self):
        s = FakeStore()
        self._make_closed_epic(s, "epic1")
        self._make_closed_epic(s, "epic2")
        self._make_closed_epic(s, "epic3")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=2))
        self.assertEqual(resp.reflection_count, 2)
        self.assertEqual(len(resp.item_signals), 2)

    def test_last_1_gives_most_recent_epic(self):
        s = FakeStore()
        self._make_closed_epic(s, "older")
        self._make_closed_epic(s, "newer")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=1))
        self.assertEqual(resp.reflection_count, 1)

    def test_last_label_in_response(self):
        s = FakeStore()
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=3))
        self.assertEqual(resp.subject, "last:3")

    def test_last_more_than_available_returns_all(self):
        s = FakeStore()
        self._make_closed_epic(s, "only theme")
        resp = RetroUseCase(s, _flow(s)).execute(RetroInput(last=5))
        self.assertEqual(resp.reflection_count, 1)


class TestWorklog(unittest.TestCase):
    def _now(self):
        n = datetime.datetime.now().astimezone()
        return n.date(), n.tzinfo

    def test_lists_stories_closed_in_period(self):
        s = FakeStore()
        sid = s.create_item("shipped item", theme=s.create_theme("theme"))
        s.close(sid, "merged")
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertIn(sid, [e.id for e in resp.entries])

    def test_empty_when_nothing_closed(self):
        s = FakeStore()
        s.create_item("still open", theme=s.create_theme("theme"))
        today, tz = self._now()
        resp = WorklogUseCase(s).execute(WorklogInput(period_args=[], today=today, tz=tz))
        self.assertEqual(resp.entries, [])


if __name__ == "__main__":
    unittest.main()
