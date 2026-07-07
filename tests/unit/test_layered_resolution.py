import os
import tempfile
import unittest
from pathlib import Path

from the_grid.adapters.fsio import FsAdapter


class _Cfg:
    def __init__(self, data, lib):
        self._data = data
        self._lib = lib

    def data_root(self):
        return self._data

    def library_root(self):
        return self._lib


def _layers():
    data, lib = tempfile.mkdtemp(), tempfile.mkdtemp()
    for base in (data, lib):
        os.makedirs(os.path.join(base, "steps"))
        os.makedirs(os.path.join(base, "workflows"))
    return FsAdapter(_Cfg(data, lib)), Path(data), Path(lib)


class TestLayeredResolution(unittest.TestCase):
    def test_grid_home_step_shadows_the_packaged_default(self):
        fs, data, lib = _layers()
        (lib / "steps" / "coder.md").write_text("---\nmodel: sonnet\n---\ndefault")
        (data / "steps" / "coder.md").write_text("---\nmodel: opus\n---\noverride")
        step = fs.parse_step("coder")
        self.assertEqual(step["body"], "override")
        self.assertEqual(step["meta"]["model"], "opus")

    def test_default_used_when_no_override(self):
        fs, data, lib = _layers()
        (lib / "steps" / "coder.md").write_text("---\nmodel: sonnet\n---\ndefault")
        self.assertEqual(fs.parse_step("coder")["body"], "default")

    def test_grid_home_workflow_shadows_the_default(self):
        fs, data, lib = _layers()
        (lib / "workflows" / "standard.md").write_text("entry: build\n")
        (data / "workflows" / "standard.md").write_text("entry: coder\n")
        self.assertIn("entry: coder", fs.workflow_text("standard"))

    def test_step_roles_unions_across_layers(self):
        fs, data, lib = _layers()
        (lib / "steps" / "coder.md").write_text("x")
        (data / "steps" / "custom.md").write_text("y")
        self.assertEqual(fs.step_roles(), ["coder", "custom"])

    def test_driver_md_is_overridable_too(self):
        fs, data, lib = _layers()
        (lib / "driver.md").write_text("---\nmodel: opus\n---\ndefault seat")
        (data / "driver.md").write_text("---\nmodel: opus\n---\nmy seat")
        self.assertEqual(fs.read_md("driver.md")["body"], "my seat")
