import unittest

from lightcycle.application.work.open_artifact import OpenArtifactInput, OpenArtifactUseCase
from tests.support.fake_fs import FakeFs
from tests.support.tui_harness import FakeLauncher


class TestOpenArtifactUseCase(unittest.TestCase):
    def test_url_opens_via_the_launcher(self):
        launcher = FakeLauncher()
        use_case = OpenArtifactUseCase(FakeFs(), launcher)
        result = use_case.execute(OpenArtifactInput(kind="url", value="https://gh/pr/1"))
        self.assertTrue(result.success)
        self.assertIn("https://gh/pr/1", result.message)
        self.assertEqual(launcher.opened_urls, ["https://gh/pr/1"])

    def test_url_that_fails_to_open_reports_failure(self):
        launcher = FakeLauncher(url_succeeds=False)
        use_case = OpenArtifactUseCase(FakeFs(), launcher)
        result = use_case.execute(OpenArtifactInput(kind="url", value="https://gh/pr/1"))
        self.assertFalse(result.success)
        self.assertIn("https://gh/pr/1", result.message)

    def test_filepath_opens_via_the_launcher_when_the_file_exists(self):
        fs = FakeFs(files={"/specs/x.md": b"x"})
        launcher = FakeLauncher()
        use_case = OpenArtifactUseCase(fs, launcher)
        result = use_case.execute(OpenArtifactInput(kind="filepath", value="/specs/x.md"))
        self.assertTrue(result.success)
        self.assertEqual(launcher.opened_paths, ["/specs/x.md"])

    def test_filepath_that_no_longer_exists_never_calls_the_launcher(self):
        launcher = FakeLauncher()
        use_case = OpenArtifactUseCase(FakeFs(), launcher)
        result = use_case.execute(OpenArtifactInput(kind="filepath", value="/specs/gone.md"))
        self.assertFalse(result.success)
        self.assertIn("no longer exists", result.message)
        self.assertEqual(launcher.opened_paths, [])

    def test_filepath_that_fails_to_open_reports_failure(self):
        fs = FakeFs(files={"/specs/x.md": b"x"})
        launcher = FakeLauncher(path_succeeds=False)
        use_case = OpenArtifactUseCase(fs, launcher)
        result = use_case.execute(OpenArtifactInput(kind="filepath", value="/specs/x.md"))
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
