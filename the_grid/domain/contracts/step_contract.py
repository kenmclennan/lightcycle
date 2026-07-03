from dataclasses import dataclass
from typing import Tuple

from the_grid.domain.contracts.artifact_requirement import ArtifactRequirement


@dataclass(frozen=True)
class StepContract:
    accepts: Tuple[ArtifactRequirement, ...]
    produces: Tuple[ArtifactRequirement, ...]

    @classmethod
    def from_meta(cls, meta) -> "StepContract":
        meta = meta or {}
        return cls(
            accepts=tuple(ArtifactRequirement.from_block(meta.get("accepts"))),
            produces=tuple(ArtifactRequirement.from_block(meta.get("produces"))),
        )

    def required_inputs(self):
        return {r.type for r in self.accepts if r.required}

    def optional_inputs(self):
        return {r.type for r in self.accepts if not r.required}

    def required_outputs(self):
        return {r.type for r in self.produces if r.required}

    def missing_inputs(self, present):
        return self.required_inputs() - set(present)

    def missing_outputs(self, present):
        return self.required_outputs() - set(present)
