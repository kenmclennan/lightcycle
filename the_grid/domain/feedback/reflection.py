import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Reflection:
    task: str
    feedback: str = ""
    spec_hash: str = "unknown"

    @classmethod
    def create(cls, task, feedback="", spec_hash="unknown") -> "Reflection":
        return cls(task=task, feedback=feedback or "", spec_hash=spec_hash)

    @staticmethod
    def spec_hash_of(data) -> str:
        return hashlib.sha256(data).hexdigest()[:8]

    @classmethod
    def from_dict(cls, d: dict) -> "Reflection":
        return cls(
            task=d.get("task"),
            feedback=d.get("feedback") or "",
            spec_hash=d.get("spec_hash") or "unknown",
        )

    def as_dict(self) -> dict:
        return {"task": self.task, "feedback": self.feedback, "spec_hash": self.spec_hash}
