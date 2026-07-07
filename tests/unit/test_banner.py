import unittest

from lightcycle.banner import render_banner


class TestRenderBanner(unittest.TestCase):
    def test_plain_when_color_disabled(self):
        out = render_banner("aaa\nbbb", color=False)
        self.assertNotIn("\033", out)
        self.assertIn("aaa", out)
        self.assertIn("bbb", out)

    def test_colored_wraps_each_line_in_truecolor(self):
        out = render_banner("aaa\nbbb", color=True)
        self.assertIn("\033[", out)
        self.assertIn("38;2;", out)
        self.assertIn("aaa", out)
        self.assertIn("\033[0m", out)

    def test_gradient_runs_top_cyan_to_bottom_blue(self):
        out = render_banner("top\nmid\nbot", color=True)
        lines = out.split("\n")
        self.assertIn("38;2;0;255;255", lines[0])
        self.assertIn("38;2;45;90;255", lines[-1])

    def test_single_line_does_not_divide_by_zero(self):
        out = render_banner("solo", color=True)
        self.assertIn("38;2;0;255;255", out)
        self.assertIn("solo", out)

    def test_trailing_blank_lines_are_trimmed(self):
        out = render_banner("aaa\n\n", color=False)
        self.assertEqual(out, "aaa")


if __name__ == "__main__":
    unittest.main()
