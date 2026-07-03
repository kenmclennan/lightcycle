from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Artifact:
    type: str
    value: str
    label: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Artifact":
        return cls(type=d.get("type"), value=d.get("value"), label=d.get("label"))

    def as_dict(self) -> dict:
        d = {"type": self.type, "value": self.value}
        if self.label is not None:
            d["label"] = self.label
        return d
