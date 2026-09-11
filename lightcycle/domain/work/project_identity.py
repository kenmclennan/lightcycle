import re
from dataclasses import dataclass
from typing import Optional

_SSH_RE = re.compile(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?/?$")
_HTTPS_RE = re.compile(r"^https://github\.com/([^/]+)/(.+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class ProjectIdentity:
    owner: str
    name: str

    @property
    def full(self) -> str:
        return "%s/%s" % (self.owner, self.name)

    @property
    def default_shortcode(self) -> str:
        return self.name.upper()

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
