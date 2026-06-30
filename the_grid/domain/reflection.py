"""Reflection: a worker's freeform feedback on a task (a value object).

The feedback is read and analysed by a human or an LLM, never parsed - what
belongs in it is guided by the agent's step file, not codified here.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Reflection:
    task: str
    feedback: str = ""
    spec_hash: str = "unknown"

    @classmethod
    def from_dict(cls, d: dict) -> "Reflection":
        return cls(task=d.get("task"), feedback=d.get("feedback") or "",
                   spec_hash=d.get("spec_hash") or "unknown")

    def as_dict(self) -> dict:
        return {"task": self.task, "feedback": self.feedback, "spec_hash": self.spec_hash}
