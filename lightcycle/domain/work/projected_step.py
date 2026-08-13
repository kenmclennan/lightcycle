from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectedStep:
    id: str
    step: str
    role: str
