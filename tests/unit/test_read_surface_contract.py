import pathlib
import unittest

from lightcycle.application.flow.claim_step import ClaimResponse
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work import ShowNodeInput, ShowNodeUseCase
from lightcycle.application.work.node_read_surface import node_read_surface
from lightcycle.domain.contracts.json_surface import READ_SURFACE_EXTRA_KEYS, json_surface
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore

from lightcycle.application.workflows.prompt_check import engine_sources
from lightcycle.application.workflows.prompt_commands import json_field_reads

LIBRARY = pathlib.Path(__file__).resolve().parents[1] / "support" / "library" / "steps"


class TestStepPromptReadsResolveAgainstTheEngineSurface(unittest.TestCase):
    def test_every_field_a_library_step_reads_is_emitted(self):
        _, emitted = engine_sources()
        unresolved = []
        for path in sorted(LIBRARY.glob("*.md")):
            for read in json_field_reads(path.read_text()):
                if read["field"] not in emitted:
                    unresolved.append("%s:%d .%s" % (path.name, read["line"], read["field"]))
        self.assertEqual(unresolved, [], "step prompts read fields the engine surface omits: %s" % unresolved)

    def test_the_library_covers_both_assembly_routes(self):
        fields = set()
        for path in sorted(LIBRARY.glob("*.md")):
            fields |= {r["field"] for r in json_field_reads(path.read_text())}
        self.assertIn("spec_path", fields)
        self.assertIn("runs", fields)


class TestDeclaredSurfaceCoversWhatTheEngineEmits(unittest.TestCase):
    def _emitted(self):
        s = FakeStore()
        metas = {"reviewer": {"step": "review", "routes": {"done": "open-pr"}}}
        flow = FlowService(FakeFs(metas), s)
        item = s.create_item("st", "a description", workflow="spec-driven", shortcode="GRID")
        sid = s.create_step(stage="review", role="reviewer", item=item)
        s.add_artifact(sid, "guidance-delivered", "a/b")
        s.add_artifact(sid, "guidance-skipped", "c/d")
        s.add_artifact(sid, "session-id", "sess-1")
        keys = set()
        for node in (sid, item):
            view = ShowNodeUseCase(s, flow).execute(ShowNodeInput(step=node)).view
            keys |= set(node_read_surface(s, flow, view))
        view = ShowNodeUseCase(s, flow).execute(ShowNodeInput(step=sid)).view
        claim = ClaimResponse(
            view=view, surface=node_read_surface(s, flow, view), workspace="w", branch="b",
            spec_path="p", description="d", repo_path="r", config={"k": "v"},
        )
        return keys | set(claim.as_dict())

    def test_every_emitted_top_level_key_is_declared(self):
        self.assertEqual(sorted(self._emitted() - json_surface()), [])

    def test_the_guidance_keys_are_declared(self):
        self.assertLessEqual({"guidance_delivered", "guidance_skipped"}, json_surface())

    def test_the_declared_extra_keys_are_the_scraped_twenty_six_and_the_guidance_pair(self):
        self.assertEqual(len(READ_SURFACE_EXTRA_KEYS), 28)
