import tomllib
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Source:
    contract: int
    name: Optional[str] = None
    description: str = ""


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
    return Source(
        contract=contract,
        name=data.get("name"),
        description=data.get("description", ""),
    )
