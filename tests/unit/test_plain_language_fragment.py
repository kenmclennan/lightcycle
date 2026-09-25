import os
import re
import tempfile
import unittest

from lightcycle.adapters.workflow_bundle import WorkflowBundleAdapter, parse_step
from lightcycle.config import Config

ENGINE_PROMPTS = os.path.join(os.path.dirname(__file__), "..", "..", "lightcycle", "prompts")
ENGINE_STEPS = ["daily-summary", "audit"]


def _write(root, relpath, text):
    path = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class TestIncludeResolution(unittest.TestCase):
    def setUp(self):
        self.adapter = WorkflowBundleAdapter()

    def test_include_is_replaced_by_the_fragment_body(self):
        root = tempfile.mkdtemp()
        _write(root, "steps/a.md", "# A\n\n@include rule\n\nend\n")
        _write(root, "fragments/rule.md", "---\nx: y\n---\nthe rule\n")
        body = self.adapter.parse_step("a", root).body
        self.assertIn("the rule", body)
        self.assertNotIn("@include", body)
        self.assertNotIn("x: y", body)

    def test_fragment_in_a_later_root_resolves(self):
        first, second = tempfile.mkdtemp(), tempfile.mkdtemp()
        _write(first, "steps/a.md", "@include rule\n")
        _write(second, "fragments/rule.md", "later root rule\n")
        self.assertIn("later root rule", parse_step([first, second], "a").body)

    def test_body_without_directive_is_unchanged(self):
        root = tempfile.mkdtemp()
        text = "# A\n\nsome @include mid-line and\n  @include indented\n"
        _write(root, "steps/a.md", text)
        self.assertEqual(self.adapter.parse_step("a", root).body, text)

    def test_missing_fragment_names_fragment_and_step(self):
        root = tempfile.mkdtemp()
        _write(root, "steps/a.md", "@include nope\n")
        with self.assertRaises(ValueError) as ctx:
            self.adapter.parse_step("a", root)
        self.assertIn("nope", str(ctx.exception))
        self.assertIn("a.md", str(ctx.exception))

    def test_batch_error_names_exactly_the_step_missing_its_fragment(self):
        root = tempfile.mkdtemp()
        _write(root, "fragments/rule.md", "rule\n")
        _write(root, "steps/one.md", "@include rule\n")
        _write(root, "steps/two.md", "@include missing\n")
        _write(root, "steps/three.md", "@include rule\n")
        failed = []
        for role in ("one", "two", "three"):
            try:
                self.adapter.parse_step(role, root)
            except ValueError as e:
                failed.append(str(e))
        self.assertEqual(len(failed), 1)
        self.assertIn("two.md", failed[0])


class TestPlainLanguageFragment(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ENGINE_PROMPTS, "fragments", "plain-language.md")) as f:
            self.text = f.read()

    def test_seven_rules_in_order(self):
        numbers = re.findall(r"^\*\*(\d+)\. ", self.text, re.M)
        self.assertEqual(numbers, ["1", "2", "3", "4", "5", "6", "7"])

    def test_ceilings_match_the_binding(self):
        self.assertIn("3 paragraphs and 180 words", self.text)
        self.assertIn("4 sentences per paragraph", self.text)
        self.assertIn("30 words per sentence", self.text)

    def test_item_reference_form_is_stated(self):
        self.assertIn("`Title (LC-123)`", self.text)


class TestEnginePromptsResolve(unittest.TestCase):
    def test_each_engine_prompt_has_one_include_line_and_resolves(self):
        adapter = WorkflowBundleAdapter()
        for role in ENGINE_STEPS:
            with open(os.path.join(ENGINE_PROMPTS, "steps", "%s.md" % role)) as f:
                raw = f.read()
            self.assertEqual(raw.count("@include plain-language"), 1, role)
            body = adapter.parse_step(role, ENGINE_PROMPTS).body
            self.assertNotIn("@include", body, role)
            for n in range(1, 8):
                self.assertIn("**%d. " % n, body, role)

    def test_prompts_dropped_their_own_paragraph_limits(self):
        for role in ENGINE_STEPS:
            with open(os.path.join(ENGINE_PROMPTS, "steps", "%s.md" % role)) as f:
                raw = f.read()
            self.assertNotIn("two short paragraphs", raw, role)
            self.assertNotIn("do LC-861 first", raw, role)

    def test_summary_prompts_attach_through_a_heredoc_not_a_backslash_n(self):
        for role in ("daily-summary",):
            with open(os.path.join(ENGINE_PROMPTS, "steps", "%s.md" % role)) as f:
                raw = f.read()
            self.assertIn("<<'EOF'", raw, role)
            self.assertIn("two literal characters", raw, role)

    def test_audit_cites_rules_and_stands_outside_the_bar(self):
        with open(os.path.join(ENGINE_PROMPTS, "steps", "audit.md")) as f:
            raw = f.read()
        self.assertIn("Plain language", raw)
        self.assertIn("outside the four-part bar", raw)

    def test_audit_no_longer_names_reflections(self):
        with open(os.path.join(ENGINE_PROMPTS, "steps", "audit.md")) as f:
            raw = f.read()
        self.assertNotIn("reflection", raw.lower())

    def test_audit_step_4_reads_notes_and_park_through_lc_show(self):
        with open(os.path.join(ENGINE_PROMPTS, "steps", "audit.md")) as f:
            step_4 = next(l for l in f.read().splitlines() if l.startswith("4. Plain language"))
        for needle in ("lc show", "notes", "park", "PARK RESOLVED:"):
            self.assertIn(needle, step_4)

    def test_audit_step_5_puts_the_digest_in_the_artifact_and_a_short_summary_in_the_note(self):
        with open(os.path.join(ENGINE_PROMPTS, "steps", "audit.md")) as f:
            step_5 = next(l for l in f.read().splitlines() if l.startswith("5. "))
        self.assertNotIn("same digest", step_5)
        self.assertIn('--note "<short summary>"', step_5)
        self.assertIn("full digest is in the `findings` artifact", step_5)

    def test_config_prompts_root_is_the_engine_dir(self):
        self.assertTrue(os.path.isfile(os.path.join(Config.prompts_root(None), "fragments", "plain-language.md")))


if __name__ == "__main__":
    unittest.main()
