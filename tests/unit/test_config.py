import os
import unittest

from grid.core.config import cfg_path, projects_root, specs_root

HOME = "/home/u"


class TestCfgPath(unittest.TestCase):
    def test_default_when_absent(self):
        self.assertEqual(cfg_path({}, "projects", "/d/efault", HOME), "/d/efault")

    def test_absolute_value_kept(self):
        self.assertEqual(cfg_path({"projects": "/abs/p"}, "projects", "/d", HOME), "/abs/p")

    def test_tilde_expanded_against_home(self):
        self.assertEqual(cfg_path({"projects": "~/p"}, "projects", "/d", HOME),
                         os.path.join(HOME, "p"))

    def test_relative_joined_to_home(self):
        self.assertEqual(cfg_path({"projects": "rel/p"}, "projects", "/d", HOME),
                         os.path.join(HOME, "rel/p"))


class TestRoots(unittest.TestCase):
    def test_default_roots(self):
        self.assertEqual(projects_root({}, HOME), os.path.join(HOME, "workspace", "projects"))
        self.assertEqual(specs_root({}, HOME), os.path.join(HOME, "workspace", "specs"))

    def test_overridden_roots(self):
        cfg = {"projects": "/p", "specs": "/s"}
        self.assertEqual(projects_root(cfg, HOME), "/p")
        self.assertEqual(specs_root(cfg, HOME), "/s")


if __name__ == "__main__":
    unittest.main()
