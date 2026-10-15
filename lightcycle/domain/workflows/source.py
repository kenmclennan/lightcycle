import tomllib
from dataclasses import dataclass
from typing import Optional

from lightcycle.domain.workflows.engine_requirement import (
    EngineRequirement, parse_engine_requirement,
)


@dataclass(frozen=True)
class Source:
    contract: int
    name: Optional[str] = None
    description: str = ""
    requires_engine: Optional[EngineRequirement] = None


def parse_source_manifest(text):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError("malformed source manifest: %s" % e)
    if "contract" not in data:
        raise ValueError("source manifest is missing required 'contract'")
    contract = data["contract"]
    if not isinstance(contract, int) or isinstance(contract, bool):
        raise ValueError("source manifest 'contract' must be an integer (got %r)" % contract)
    requires_engine = None
    if "requires-engine" in data:
        try:
            requires_engine = parse_engine_requirement(data["requires-engine"])
        except ValueError as e:
            raise ValueError("source manifest 'requires-engine' %s" % e)
    return Source(
        contract=contract,
        name=data.get("name"),
        description=data.get("description", ""),
        requires_engine=requires_engine,
    )
