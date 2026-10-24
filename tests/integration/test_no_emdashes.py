import pathlib
import subprocess
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EMDASH = chr(0x2014)
ALLOWED_EMDASH_FILES = frozenset()


def tracked_files(root=REPO_ROOT):
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=60
    ).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def emdash_lines(root=REPO_ROOT, allowed=ALLOWED_EMDASH_FILES):
    hits = []
    for name in tracked_files(root):
        if name in allowed:
            continue
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if EMDASH in line:
                hits.append("%s:%d" % (name, number))
    return hits


class TestNoEmdashesInTrackedText(unittest.TestCase):
    def test_no_tracked_text_file_holds_an_emdash_and_the_allow_list_is_empty(self):
        self.assertEqual(ALLOWED_EMDASH_FILES, frozenset())
        self.assertEqual(emdash_lines(), [])
