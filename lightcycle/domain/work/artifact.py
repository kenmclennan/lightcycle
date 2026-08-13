from dataclasses import dataclass
from typing import Optional

_KIND_DEFAULTS = {
    "pr": "url",
    "spec": "filepath",
    "brief": "filepath",
    "repo": "text",
    "branch": "text",
}


def default_kind_for(atype: str) -> str:
    return _KIND_DEFAULTS.get(atype, "text")


@dataclass(frozen=True)
class Artifact:
    type: str
    value: str
    label: Optional[str] = None
    internal: bool = False
    kind: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        return cls(
            type=d.get("type"), value=d.get("value"), label=d.get("label"),
            internal=d.get("internal", False), kind=d.get("kind"),
        )

    def as_dict(self) -> dict:
        d = {"type": self.type, "value": self.value}
        if self.label is not None:
            d["label"] = self.label
        if self.internal:
            d["internal"] = self.internal
        if self.kind is not None:
            d["kind"] = self.kind
        return d
