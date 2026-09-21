import re
from dataclasses import dataclass
from typing import Optional

_SSH_RE = re.compile(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?/?$")
_HTTPS_RE = re.compile(r"^https://github\.com/([^/]+)/(.+?)(?:\.git)?/?$")

RESERVED_SHORTCODES = frozenset({"G"})


def reserved_shortcode_reason(shortcode: str) -> Optional[str]:
    if shortcode.upper() in RESERVED_SHORTCODES:
        return "shortcode '%s' is reserved: goal ids are G-<n>, so an item G-<n> would read as a goal" % shortcode
    return None


@dataclass(frozen=True)
class ProjectIdentity:
    owner: str
    name: str

    @property
    def full(self) -> str:
        return "%s/%s" % (self.owner, self.name)

    @property
    def default_shortcode(self) -> str:
        candidate = self.name.upper()
        if candidate in RESERVED_SHORTCODES:
            return (self.owner + self.name).upper()
        return candidate

    @classmethod
    def parse(cls, raw: str) -> "ProjectIdentity":
        if raw.count("/") != 1 or not all(raw.split("/")):
            raise ValueError("project identity must be 'owner/name' (got %r)" % raw)
        owner, name = raw.split("/")
        return cls(owner, name)

    @staticmethod
    def short_name(raw: str) -> str:
        return raw.rsplit("/", 1)[-1]

    @classmethod
    def from_remote_url(cls, remote: str) -> Optional["ProjectIdentity"]:
        if not remote:
            return None
        for pattern in (_SSH_RE, _HTTPS_RE):
            m = pattern.match(remote.strip())
            if m:
                return cls(m.group(1), m.group(2))
        return None
