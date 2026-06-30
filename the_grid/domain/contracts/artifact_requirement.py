"""ArtifactRequirement: one accepts/produces entry of a step contract (a value object)."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactRequirement:
    type: str
    required: bool

    @staticmethod
    def from_block(block):
        """Parse a frontmatter accepts/produces block into requirements. An entry whose
        value is the literal "optional" is optional; anything else is required."""
        if not isinstance(block, dict):
            return []
        return [ArtifactRequirement(type=t, required=str(v).strip().lower() != "optional")
                for t, v in block.items()]
