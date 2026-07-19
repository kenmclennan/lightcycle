from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Problem:
    category: str
    message: str
    node_id: Optional[str] = None

    def as_dict(self) -> dict:
        d = {"category": self.category, "message": self.message}
        if self.node_id is not None:
            d["node_id"] = self.node_id
        return d
