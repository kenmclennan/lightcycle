import json
import unittest

from the_grid.application.feedback import Reflect, Retro
from tests.fake_fs import FakeFs
from tests.fake_store import FakeStore


class TestReflect(unittest.TestCase):
    def test_records_reflection_on_the_task_with_spec_hash(self):
        s = FakeStore()
        story = s.create_story("st")
        s.add_artifact(story, "spec", "/specs/x.md")
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        fs = FakeFs(files={"/specs/x.md": b"spec body"})
        Reflect(s, fs).execute(k, "went well")
        refl = json.loads(s.story_artifacts(k)[0]["value"])
        self.assertEqual(refl["task"], k)
        self.assertEqual(refl["feedback"], "went well")
        self.assertNotEqual(refl["spec_hash"], "unknown")

    def test_unknown_spec_hash_when_no_spec(self):
        s = FakeStore()
        k = s.create_task("loose task", role="human")
        Reflect(s, FakeFs()).execute(k, "fb")
        refl = json.loads(s.story_artifacts(k)[0]["value"])
        self.assertEqual(refl["spec_hash"], "unknown")


class TestRetro(unittest.TestCase):
    def test_gathers_feedback_and_signals(self):
        s = FakeStore()
        epic = s.create_story("epic")
        story = s.create_story("st", epic=epic)
        k = s.create_task("build: x", step="build", role="coder", parent=story)
        s.add_artifact(k, "reflection", json.dumps({"task": k, "feedback": "fb1", "spec_hash": "h"}))
        digest = Retro(s).execute(epic)
        self.assertEqual(digest["n"], 1)
        self.assertEqual(digest["feedback"][0]["feedback"], "fb1")
        self.assertEqual(len(digest["story_signals"]), 1)
        self.assertEqual(digest["story_signals"][0]["nrefs"], 1)

    def test_empty_when_no_reflections(self):
        s = FakeStore()
        epic = s.create_story("epic")
        s.create_story("st", epic=epic)
        digest = Retro(s).execute(epic)
        self.assertEqual(digest["n"], 0)
        self.assertEqual(digest["feedback"], [])


if __name__ == "__main__":
    unittest.main()
