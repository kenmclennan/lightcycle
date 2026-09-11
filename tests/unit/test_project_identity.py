import unittest

from lightcycle.domain.work import ProjectIdentity


class TestParse(unittest.TestCase):
    def test_parses_owner_and_name(self):
        identity = ProjectIdentity.parse("acme/horde")
        self.assertEqual(identity, ProjectIdentity("acme", "horde"))

    def test_full_round_trips(self):
        self.assertEqual(ProjectIdentity.parse("acme/horde").full, "acme/horde")

    def test_raises_on_no_slash(self):
        with self.assertRaisesRegex(
            ValueError, r"project identity must be 'owner/name' \(got 'specs'\)"
        ):
            ProjectIdentity.parse("specs")

    def test_raises_on_more_than_one_slash(self):
        with self.assertRaisesRegex(
            ValueError, r"project identity must be 'owner/name' \(got 'a/b/c'\)"
        ):
            ProjectIdentity.parse("a/b/c")

    def test_raises_on_empty_owner(self):
        with self.assertRaisesRegex(
            ValueError, r"project identity must be 'owner/name' \(got '/name'\)"
        ):
            ProjectIdentity.parse("/name")

    def test_raises_on_empty_name(self):
        with self.assertRaisesRegex(
            ValueError, r"project identity must be 'owner/name' \(got 'owner/'\)"
        ):
            ProjectIdentity.parse("owner/")


class TestShortName(unittest.TestCase):
    def test_short_name_of_a_valid_identity(self):
        self.assertEqual(ProjectIdentity.short_name("acme/horde"), "horde")

    def test_short_name_of_a_bare_non_owner_name_string(self):
        self.assertEqual(ProjectIdentity.short_name("specs"), "specs")


class TestDefaultShortcode(unittest.TestCase):
    def test_default_shortcode_of_a_parsed_identity(self):
        self.assertEqual(ProjectIdentity.parse("acme/horde").default_shortcode, "HORDE")


class TestFromRemoteUrl(unittest.TestCase):
    def test_ssh_form(self):
        self.assertEqual(
            ProjectIdentity.from_remote_url("git@github.com:acme/horde.git"),
            ProjectIdentity("acme", "horde"),
        )

    def test_https_form_with_git_suffix(self):
        self.assertEqual(
            ProjectIdentity.from_remote_url("https://github.com/acme/horde.git"),
            ProjectIdentity("acme", "horde"),
        )

    def test_https_form_without_git_suffix(self):
        self.assertEqual(
            ProjectIdentity.from_remote_url("https://github.com/acme/horde"),
            ProjectIdentity("acme", "horde"),
        )

    def test_https_form_with_trailing_slash(self):
        self.assertEqual(
            ProjectIdentity.from_remote_url("https://github.com/acme/horde/"),
            ProjectIdentity("acme", "horde"),
        )

    def test_non_github_remote_returns_none(self):
        self.assertIsNone(ProjectIdentity.from_remote_url("https://gitlab.com/acme/horde.git"))

    def test_none_remote_returns_none(self):
        self.assertIsNone(ProjectIdentity.from_remote_url(None))

    def test_empty_remote_returns_none(self):
        self.assertIsNone(ProjectIdentity.from_remote_url(""))


if __name__ == "__main__":
    unittest.main()
