import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass

_REMOTE_INIT_URL = "https://raw.githubusercontent.com/kenmclennan/lightcycle/main/lightcycle/__init__.py"
_INSTALL_CMD = ["pipx", "install", "--force", "git+https://github.com/kenmclennan/lightcycle"]
_VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


@dataclass(frozen=True)
class UpgradeResponse:
    current: str
    remote: str
    available: bool
    applied: bool


def parse_remote_version(text):
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def fetch_remote_version():
    with urllib.request.urlopen(_REMOTE_INIT_URL, timeout=10) as resp:
        version = parse_remote_version(resp.read().decode())
    if version is None:
        raise ValueError("no __version__ found in the remote file")
    return version


def install_upgrade():
    env = dict(os.environ, UV_VENV_CLEAR="1")
    subprocess.run(_INSTALL_CMD, check=True, env=env)


def _semver(version):
    return tuple(int(part) for part in version.split("."))


def upgrade(current_version, check_only=False, fetch=fetch_remote_version, install=install_upgrade):
    remote_version = fetch()
    available = _semver(remote_version) > _semver(current_version)
    applied = False
    if available and not check_only:
        install()
        applied = True
    return UpgradeResponse(
        current=current_version, remote=remote_version, available=available, applied=applied
    )
