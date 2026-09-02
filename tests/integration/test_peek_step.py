import os
import tempfile
import unittest

from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.peek_step import PeekStepInput, PeekStepUseCase
from tests.support.fake_fs import FakeFs
from tests.support.fake_store import FakeStore


class FakeConfig:
    def __init__(self, data_root, prompts_root):
        self._data_root = data_root
        self._prompts_root = prompts_root

    def data_root(self):
        return self._data_root

    def prompts_root(self):
        return self._prompts_root


def _write_bundle(checkout_dir, role, body):
    with open(os.path.join(checkout_dir, "source.toml"), "w") as f:
        f.write('name = "acme"\ncontract = 1\n')
    os.makedirs(os.path.join(checkout_dir, "workflows"), exist_ok=True)
    os.makedirs(os.path.join(checkout_dir, "steps"), exist_ok=True)
    with open(os.path.join(checkout_dir, "steps", "%s.md" % role), "w") as f:
        f.write("---\nmodel: x\n---\n%s\n" % body)


class TestPeekStepUseCaseReadsTheOriginsCurrentBundle(unittest.TestCase):
    def test_returns_the_current_sha_body_not_the_frozen_historical_one(self):
        config = FakeConfig(tempfile.mkdtemp(), tempfile.mkdtemp())
        adapter = WorkflowSourceAdapter(config)

        old_checkout = tempfile.mkdtemp()
        _write_bundle(old_checkout, "write-code", "old body")
        adapter.materialize("acme", "sha-old", old_checkout)

        new_checkout = tempfile.mkdtemp()
        _write_bundle(new_checkout, "write-code", "new body")
        adapter.materialize("acme", "sha-new", new_checkout)

        adapter.write_registry("acme", "https://example.invalid/acme", "main", "sha-new")

        store = FakeStore()
        item = store.create_item("an item", "a description", workflow="acme/build@sha-old")
        flow = FlowService(FakeFs(), store, config, adapter)

        resp = PeekStepUseCase(store, flow, config, adapter).execute(
            PeekStepInput(node_id=item, stage="write-code"))

        self.assertEqual(resp.pin, "acme/build@sha-new")
        self.assertEqual(resp.body.strip(), "new body")


if __name__ == "__main__":
    unittest.main()
