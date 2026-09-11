import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_NAMES = ("source.toml", "CLAUDE.md", "simulate.yml", "README.md")


class TestTemplatesShipWithInstalledPackage(unittest.TestCase):
    def test_read_template_matches_checkout_from_installed_wheel(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist_dir = Path(tmp) / "dist"
            venv_dir = Path(tmp) / "venv"

            subprocess.run(
                ["uv", "build", "--wheel", "-o", str(dist_dir)],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )
            wheels = list(dist_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1, "expected exactly one built wheel")

            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_dir)],
                check=True, capture_output=True, text=True,
            )
            venv_python = venv_dir / "bin" / "python"
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", str(wheels[0])],
                check=True, capture_output=True, text=True,
            )

            for name in TEMPLATE_NAMES:
                result = subprocess.run(
                    [
                        str(venv_python), "-c",
                        "from lightcycle.adapters.scaffold import ScaffoldAdapter; "
                        "import sys; sys.stdout.write(ScaffoldAdapter().read_template(sys.argv[1]))",
                        name,
                    ],
                    check=True, capture_output=True, text=True,
                )
                expected = (REPO_ROOT / "lightcycle" / "templates" / "origin" / name).read_text()
                self.assertEqual(result.stdout, expected)


if __name__ == "__main__":
    unittest.main()
