import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

import lightcycle.cli as cli_mod
from lightcycle.application.inspect.show_audit_criteria import ShowAuditCriteriaUseCase
from lightcycle.cli import cmd_audit_criteria
from lightcycle.container import Container
from lightcycle.domain.work.audit_criteria import UnknownMaterial, material_criteria
from lightcycle.domain.work.worker_permissions import worker_permitted
from tests.support.fake_fs import FakeFs

PROMPTS = "/engine/prompts"
TEXT = (
    "# Title\n\nintro\n\n## Material: guidance\n\nG body\nline two\n\n"
    "## Material: workflows\n\nW body\n"
)


class _Config:
    def prompts_root(self):
        return PROMPTS


class TestAuditCriteriaCli(unittest.TestCase):
    def setUp(self):
        self._orig = cli_mod._container
        self.addCleanup(lambda: cli_mod.set_container(self._orig))

    def _run(self, argv, text=TEXT):
        fs = FakeFs(files={PROMPTS + "/steps/material-audit.md": text.encode()})
        cli_mod.set_container(Container(
            config=_Config(), git=object(), store=object(), spawner=object(),
            workers=object(), fs=fs, github=object(), lock=object(), breaker=object(),
        ))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmd_audit_criteria(argv) or 0
        return rc, out.getvalue(), err.getvalue()

    def test_workflows_prints_its_section_body(self):
        rc, out, err = self._run(["workflows"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "W body\n")

    def test_guidance_prints_the_other_section(self):
        rc, out, err = self._run(["guidance"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "G body\nline two\n")

    def test_unknown_token_fails_naming_known_tokens_with_empty_stdout(self):
        rc, out, err = self._run(["nope"])
        self.assertNotEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertIn("guidance", err)
        self.assertIn("workflows", err)

    def test_use_case_reads_through_the_fs_port(self):
        fs = FakeFs(files={PROMPTS + "/steps/material-audit.md": TEXT.encode()})
        self.assertEqual(ShowAuditCriteriaUseCase(fs, _Config()).execute("workflows"), "W body")

    def test_audit_criteria_is_not_a_worker_verb(self):
        self.assertFalse(worker_permitted("audit-criteria", {}))


class TestMaterialCriteria(unittest.TestCase):
    def test_last_section_runs_to_end_of_file(self):
        self.assertEqual(material_criteria("## Material: a\n\nbody\nmore\n", "a"), "body\nmore")

    def test_heading_with_no_body_is_empty(self):
        self.assertEqual(material_criteria("## Material: a\n## Material: b\nx\n", "a"), "")

    def test_unknown_names_known_tokens(self):
        with self.assertRaises(UnknownMaterial) as ctx:
            material_criteria(TEXT, "x")
        self.assertEqual(ctx.exception.known, ("guidance", "workflows"))


if __name__ == "__main__":
    unittest.main()
