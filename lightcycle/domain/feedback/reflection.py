import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Reflection:
    step: str
    feedback: str = ""
    spec_hash: str = "unknown"

    @classmethod
    def create(cls, step, feedback="", spec_hash="unknown") -> "Reflection":
        return cls(step=step, feedback=feedback or "", spec_hash=spec_hash)

    @staticmethod
    def spec_hash_of(data) -> str:
        return hashlib.sha256(data).hexdigest()[:8]

    @classmethod
    def from_dict(cls, d: dict) -> "Reflection":
        return cls(
            step=d.get("step"),
            feedback=d.get("feedback") or "",
            spec_hash=d.get("spec_hash") or "unknown",
        )

    def as_dict(self) -> dict:
        return {"step": self.step, "feedback": self.feedback, "spec_hash": self.spec_hash}


def parse_reflections(artifacts):
    out, unreadable = [], []
    for a in artifacts:
        if a.type != "reflection":
            continue
        try:
            out.append(Reflection.from_dict(json.loads(a.value)))
        except (ValueError, KeyError):
            unreadable.append(a.value)
    return out, unreadable


def reflections_of(item_artifacts, steps, retroed_pass_ids):
    out = [a for a in item_artifacts if a.type == "reflection"]
    for pass_id, artifacts in steps:
        if pass_id in retroed_pass_ids:
            continue
        out.extend(a for a in artifacts if a.type == "reflection")
    return out
