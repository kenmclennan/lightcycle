import re
import unittest
from pathlib import Path

from lightcycle.domain.work.audit_criteria import material_criteria

PROMPT = Path(__file__).resolve().parents[2] / "lightcycle" / "prompts" / "steps" / "material-audit.md"

LEADING_PHRASES = (
    "Provenance in a prompt",
    "True for one user or stack",
    "A rule that gets lost",
    "References that are wrong in some workflow",
    "Copy drift",
    "A step that does not stand alone",
    "An outcome with no edge",
    "A rule a check could enforce",
)

VERB_WORDS = ("strip", "move", "shorten", "rewrite", "list", "add", "valid_outcomes")


class TestMaterialAuditPrompt(unittest.TestCase):
    def setUp(self):
        self.text = PROMPT.read_text()
        self.section = material_criteria(self.text, "workflows")

    def test_prompt_has_a_workflows_heading(self):
        self.assertIn("## Material: workflows", self.text)

    def test_section_carries_each_of_the_eight_criteria(self):
        for phrase in LEADING_PHRASES:
            self.assertIn(phrase, self.section)

    def test_section_carries_each_verdict_word(self):
        for word in VERB_WORDS:
            self.assertRegex(self.section, r"\b%s" % re.escape(word))

    def test_section_names_the_two_commands_a_worker_can_run(self):
        self.assertIn("lc workflow check --dir", self.section)
        self.assertIn("lc workflow list", self.section)

    def test_guidance_section_no_longer_ends_the_audit_clean(self):
        guidance = material_criteria(self.text, "guidance")
        self.assertNotIn("finish `clean`", guidance)

    def test_guidance_section_names_the_promotion_destination_and_drops_the_item_id(self):
        guidance = material_criteria(self.text, "guidance")
        self.assertIn("Promotion candidate", guidance)
        self.assertIn("guidance-entry", guidance)
        self.assertNotIn("LC-669", guidance)

    def test_workflows_section_says_all_eight(self):
        self.assertIn("all eight", self.section)

    def test_both_materials_resolve_to_non_empty_text(self):
        self.assertEqual(
            len(re.findall(r"^## Material: ", self.text, re.M)), 2)
        self.assertTrue(material_criteria(self.text, "guidance"))
        self.assertTrue(self.section)


if __name__ == "__main__":
    unittest.main()
