import json
import os
import tempfile
import unittest

from lightcycle.adapters.guidance_sync_status import GuidanceSyncStatusAdapter
from lightcycle.domain.pool import GuidanceSyncState


class FakeConfig:
    def __init__(self, root):
        self._root = root

    def data_root(self):
        return self._root


class TestGuidanceSyncStatusAdapter(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.path = os.path.join(self.root, "logs", "guidance_sync.json")
        self.status = GuidanceSyncStatusAdapter(FakeConfig(self.root))

    def _write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            f.write(text)

    def test_load_with_no_state_file_is_none(self):
        self.assertIsNone(self.status.load())

    def test_save_then_load_round_trips(self):
        state = GuidanceSyncState(ok=True, at=100.0, detail="fetched", ref="origin/main")
        self.status.save(state)
        self.assertEqual(self.status.load(), state)

    def test_the_file_carries_the_key_set_written_before_the_named_type(self):
        self.status.save(GuidanceSyncState(ok=True, at=1.0))
        with open(self.path) as f:
            self.assertEqual(set(json.load(f)), {"ok", "at", "detail", "ref"})

    def test_a_failed_save_with_no_ref_reads_back_with_no_ref(self):
        self.status.save(GuidanceSyncState(ok=False, at=5.0, detail="offline"))
        loaded = self.status.load()
        self.assertFalse(loaded.ok)
        self.assertIsNone(loaded.ref)

    def test_invalid_json_loads_as_none(self):
        self._write("{not json")
        self.assertIsNone(self.status.load())

    def test_a_json_list_loads_as_none(self):
        self._write("[1, 2]")
        self.assertIsNone(self.status.load())


if __name__ == "__main__":
    unittest.main()
