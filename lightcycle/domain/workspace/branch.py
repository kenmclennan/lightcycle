import re
from dataclasses import dataclass

_SLUG_LIMIT = 40


@dataclass(frozen=True)
class Branch:
    name: str

    @classmethod
    def for_feature(cls, feature: str, prefix: str = "feat", ident: str = "") -> "Branch":
        slug = cls._slugify(feature, limit=_SLUG_LIMIT)
        if not ident:
            return cls(name="%s/%s" % (prefix, slug))
        if not slug:
            return cls(name="%s/%s" % (prefix, ident))
        return cls(name="%s/%s-%s" % (prefix, ident, slug))

    @staticmethod
    def _slugify(text: str, limit: int = None) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        if limit is not None and len(slug) > limit:
            truncated = slug[:limit]
            if "-" in truncated:
                truncated = truncated.rsplit("-", 1)[0]
            slug = truncated.strip("-")
        return slug
