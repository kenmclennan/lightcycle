import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Branch:
    name: str

    @classmethod
    def for_feature(cls, feature: str, prefix: str = "feat") -> "Branch":
        return cls(name="%s/%s" % (prefix, cls._slugify(feature)))

    @staticmethod
    def _slugify(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
