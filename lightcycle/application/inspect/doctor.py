from dataclasses import dataclass
from typing import Dict, List

from lightcycle.domain.health import Problem, fsck
from lightcycle.domain.work.state import State
from lightcycle.domain.workflows.contract import ENGINE_CONTRACT, contract_compatible
from lightcycle.domain.workflows.identity import format_pin, parse_pin
from lightcycle.domain.workflows.source import parse_source_manifest


@dataclass(frozen=True)
class DoctorInput:
    pass


@dataclass(frozen=True)
class DoctorReport:
    problems: Dict[str, List[Problem]]

    def healthy(self) -> bool:
        return not any(self.problems.values())


class DoctorUseCase:
    def __init__(self, store, workflow_source, config):
        self._store = store
        self._workflow_source = workflow_source
        self._config = config

    def execute(self, input: DoctorInput) -> DoctorReport:
        nodes = self._store.all_nodes_including_done()
        pins, contracts = self._bundle_problems(nodes)
        return DoctorReport(problems={
            "store": fsck(nodes),
            "pins": pins,
            "contract": contracts,
            "origin": self._origin_problems(),
            "config": self._config_problems(),
        })

    def _in_flight_pins(self, nodes):
        for n in nodes:
            if n.type != "item" or n.state == State.DONE:
                continue
            parsed = parse_pin(n.workflow)
            if parsed:
                yield n, parsed

    def _bundle_problems(self, nodes):
        pins, contracts = [], []
        for n, (origin, name, sha) in self._in_flight_pins(nodes):
            pin = format_pin(origin, name, sha)
            if not self._workflow_source.has_version(origin, sha):
                pins.append(Problem("pins", "pinned bundle %s no longer resolves on disk" % pin, n.id))
                continue
            bundle = self._workflow_source.bundle_path(origin, sha)
            manifest = parse_source_manifest(self._workflow_source.read_manifest(bundle))
            if not contract_compatible(manifest.contract):
                contracts.append(Problem(
                    "contract",
                    "%s has contract %d, engine is %d" % (pin, manifest.contract, ENGINE_CONTRACT),
                    n.id,
                ))
        return pins, contracts

    def _origin_problems(self):
        if "default-origin" in self._config.missing_config_keys():
            return []
        origin = self._config.default_origin()
        if self._workflow_source.current_sha(origin) is None:
            return [Problem("origin", "default-origin %r is set but has no pulled bundle" % origin)]
        return []

    def _config_problems(self):
        return [
            Problem("config", "required config key %r is not set" % k)
            for k in self._config.missing_config_keys()
        ]
