import pathlib
import unittest

from lightcycle.adapters.fsio import FsAdapter
from lightcycle.application.workflows.prompt_check import engine_sources
from lightcycle.application.workflows.prompt_commands import json_field_reads
from lightcycle.config import Config

LIBRARY = pathlib.Path(__file__).resolve().parents[1] / "support" / "library" / "steps"


class TestStepPromptReadsResolveAgainstTheEngineSurface(unittest.TestCase):
    def test_every_field_a_library_step_reads_is_emitted(self):
        _, emitted = engine_sources(FsAdapter(Config()))
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
