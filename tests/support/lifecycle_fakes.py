from lightcycle.application.workflows.lifecycle import WorkflowLifecycleService
from tests.support.fake_fs import FakeFs
from tests.support.fake_lifecycle_runner import FakeLifecycleRunner


class LifecycleFakeConfig:
    def __init__(self, blocks=None, timeout=300, data_root="/data", env=None):
        self._blocks = blocks or {}
        self._timeout = timeout
        self._data_root = data_root
        self._env = env or {}

    def agent_env(self):
        return dict(self._env)

    def lifecycle_timeout_seconds(self):
        return self._timeout

    def workflow_data_dir(self, origin, name):
        return "%s/workflow-data/%s/%s" % (self._data_root, origin, name)

    def workflow_config_block_name(self, origin, name):
        return "workflow-%s-%s" % (origin, name)

    def workflow_config(self, origin, name):
        return dict(self._blocks.get(self.workflow_config_block_name(origin, name), {}))


def lifecycle_for(source, bundle=None, config=None, runner=None):
    return WorkflowLifecycleService(
        source,
        bundle if bundle is not None else FakeFs(),
        config if config is not None else LifecycleFakeConfig(),
        runner if runner is not None else FakeLifecycleRunner(),
    )
