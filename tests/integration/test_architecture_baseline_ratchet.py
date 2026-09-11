import pathlib
import tomllib
import unittest

from tests.support.baseline_counts import grown_entries, parse_counts
from tests.support.git_ref import read_at_ref

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

BASELINE_FILES = [
    "tests/unit/baselines/subprocess_timeout.txt",
    "tests/unit/baselines/atomic_json_write.txt",
]

RATCHET_CODES = {"BLE001", "RUF013", "DTZ", "SIM115"}

LAYER_POLICY_EXEMPTIONS = {
    ("tests/**", "BLE001"),
    ("tests/**", "RUF013"),
    ("tests/**", "DTZ"),
    ("tests/**", "SIM115"),
    ("lightcycle/adapters/**", "BLE001"),
    ("lightcycle/cli.py", "BLE001"),
    ("lightcycle/container.py", "BLE001"),
    ("lightcycle/config.py", "BLE001"),
    ("lightcycle/render.py", "BLE001"),
    ("lightcycle/ports/**", "BLE001"),
    ("lightcycle/__main__.py", "BLE001"),
}


def _ratchet_pairs(per_file_ignores):
    pairs = set()
    for glob, codes in per_file_ignores.items():
        for code in codes:
            if code in RATCHET_CODES:
                pairs.add((glob, code))
    return pairs - LAYER_POLICY_EXEMPTIONS


def _lint_config(toml_text):
    config = tomllib.loads(toml_text)
    return config.get("tool", {}).get("ruff", {}).get("lint", {})


class TestBaselineCountsHaveNotGrown(unittest.TestCase):
    def test_committed_baselines_do_not_exceed_origin_main(self):
        for rel_path in BASELINE_FILES:
            main_text = read_at_ref("origin/main", rel_path)
            if main_text is None:
                self.skipTest("origin/main not resolvable locally for %s" % rel_path)
            before = parse_counts(main_text)
            after = parse_counts((REPO_ROOT / rel_path).read_text())
            grown = grown_entries(before, after)
            self.assertEqual(grown, {}, "%s grew past origin/main: %s" % (rel_path, grown))


class TestRuffBaselineHasNotGrown(unittest.TestCase):
    def test_per_file_ignores_do_not_gain_a_new_baseline_pair(self):
        main_text = read_at_ref("origin/main", "pyproject.toml")
        if main_text is None:
            self.skipTest("origin/main not resolvable locally for pyproject.toml")
        main_lint = _lint_config(main_text)
        if "per-file-ignores" not in main_lint:
            self.skipTest("origin/main has no per-file-ignores table yet - ratchet not yet established")
        head_lint = _lint_config((REPO_ROOT / "pyproject.toml").read_text())
        main_pairs = _ratchet_pairs(main_lint["per-file-ignores"])
        head_pairs = _ratchet_pairs(head_lint.get("per-file-ignores", {}))
        added = head_pairs - main_pairs
        self.assertEqual(added, set(), "ruff baseline gained new pair(s): %s" % added)


class TestGrownEntriesAgainstReadAtRef(unittest.TestCase):
    def test_a_constructed_growth_is_detected(self):
        before = {"x.py": 1}
        after = {"x.py": 2}
        self.assertEqual(grown_entries(before, after), {"x.py": (1, 2)})


if __name__ == "__main__":
    unittest.main()
