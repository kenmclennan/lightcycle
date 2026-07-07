import hashlib
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
