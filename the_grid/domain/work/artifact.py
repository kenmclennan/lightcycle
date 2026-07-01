"""Artifact: a typed reference attached to a story (spec, branch, pr, repo, ...).

A value object. Stored in the task's metadata as a plain dict, so it hydrates with
from_dict and serialises (for the JSON views) with as_dict.
"""
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
