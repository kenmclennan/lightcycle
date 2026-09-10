import tempfile
import unittest

from lightcycle.adapters.workflow_source import WorkflowSourceAdapter
from lightcycle.application.services.flow import FlowService
from lightcycle.application.work.peek_step import PeekStepInput, PeekStepUseCase
from lightcycle.ports.workflow_source import FetchedBundle
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


class TestPeekStepUseCaseReadsTheOriginsCurrentBundle(unittest.TestCase):
    def test_returns_the_current_sha_body_not_the_frozen_historical_one(self):
        config = FakeConfig(tempfile.mkdtemp(), tempfile.mkdtemp())
        adapter = WorkflowSourceAdapter(config)

        adapter.pin("acme", FetchedBundle(
            manifest='name = "acme"\ncontract = 1\n', sha="sha-old",
            steps={"write-code": "---\nmodel: x\n---\nold body\n"}, workflows={}))

        adapter.pin("acme", FetchedBundle(
            manifest='name = "acme"\ncontract = 1\n', sha="sha-new",
            steps={"write-code": "---\nmodel: x\n---\nnew body\n"}, workflows={}))

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
