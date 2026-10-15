from lightcycle.application.pool.schedule_cadence import ScheduleCadenceUseCase
from lightcycle.config import ConfigValueError
from lightcycle.domain.work import State
from tests.support.fake_git import FakeGit
from tests.support.fake_store import FakeStore


class StubConfig:
    def __init__(self, blocks=None, paused="false"):
        self.blocks = blocks or {}
        self.paused = paused

    def schedule_blocks(self):
        return {k: dict(v) for k, v in self.blocks.items()}

    def schedules_paused(self):
        text = str(self.paused).strip().lower()
        if text in ("true", "yes", "1", "on"):
            return True
        if text in ("false", "no", "0", "off"):
            return False
        raise ConfigValueError("schedules-paused must be true or false")


class StubFlow:
    def __init__(self, workflows=None):
        self.workflows = workflows if workflows is not None else {"lightcycle/audit": {}}
        self.meta_reads = 0

    def _name(self, pin):
        return pin.split("@")[0]

    def resolve_selection(self, selector):
        if self._name(selector) not in self.workflows:
            raise ValueError("origin has no workflow %r" % selector)
        return self._name(selector) + "@sha"

    def load_graph(self, pin):
        return None

    def workflow_meta(self, pin):
        self.meta_reads += 1
        return self.workflows.get(self._name(pin), {})


class StubWorkflowSource:
    def __init__(self, workflows=None, shas=None):
        self.workflows = workflows or {}
        self.shas = shas or {}

    def list_origins(self):
        return sorted(self.shas)

    def current_sha(self, origin):
        return self.shas.get(origin)

    def read_registry(self, origin):
        from lightcycle.ports.workflow_source import OriginRegistration
        sha = self.shas.get(origin)
        return OriginRegistration(url="u", ref="main", current=sha) if sha else None

    def workflow_names(self, origin, sha):
        return [n.split("/", 1)[1] for n in self.workflows if n.startswith(origin + "/")]


class RecordingActivate:
    def __init__(self, store, fail=None):
        self._store = store
        self.fail = fail
        self.activated = []

    def execute(self, input):
        if self.fail is not None:
            raise self.fail
        self.activated.append(input.item)
        self._store.update_state(input.item, State.QUEUED)


def block(**overrides):
    base = {
        "enabled": "true", "workflow": "lightcycle/audit", "project": "acme/app",
        "cron": "0 * * * *", "guard": "materials-changed",
    }
    base.update(overrides)
    return base


class ScheduleRig:
    def __init__(self, blocks=None, paused="false", flow=None, source=None, git=None,
                 activate_fail=None):
        self.store = FakeStore()
        self.store.add_project("acme/app", shortcode="APP", local_path="/tmp/app")
        self.config = StubConfig(blocks, paused)
        self.flow = flow or StubFlow()
        self.source = source or StubWorkflowSource(shas={"lightcycle": "sha1"})
        self.git = git or FakeGit()
        self.activate = RecordingActivate(self.store, fail=activate_fail)
        self.cadence = ScheduleCadenceUseCase(
            self.store, self.config, self.flow, self.source, self.git, self.activate)
