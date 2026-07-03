from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactRequirement:
    type: str
    required: bool

    @staticmethod
    def from_block(block):
        if not isinstance(block, dict):
            return []
        return [
            ArtifactRequirement(type=t, required=str(v).strip().lower() != "optional")
            for t, v in block.items()
        ]
