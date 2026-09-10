import re
import subprocess
import urllib.error
import urllib.request

from lightcycle.application.setup.upgrade import (
    ProcessListUnreadableError,
    RemoteVersionUnavailableError,
    parse_remote_version,
)
from lightcycle.ports.upgrade import UpgradePort

_REMOTE_INIT_URL = "https://raw.githubusercontent.com/kenmclennan/lightcycle/main/lightcycle/__init__.py"
_INSTALL_CMD = ["pipx", "install", "--force", "git+https://github.com/kenmclennan/lightcycle"]
_SEMVER_RE = re.compile(r"(\d+\.\d+\.\d+)")


class UpgradeAdapter(UpgradePort):
    def __init__(self, config):
        self._config = config

    def list_processes(self):
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,args="], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise ProcessListUnreadableError(str(e)) from e
        if result.returncode != 0:
            raise ProcessListUnreadableError("ps exited with status %d" % result.returncode)
        return result.stdout.decode()

    def fetch_remote_version(self):
        try:
            with urllib.request.urlopen(_REMOTE_INIT_URL, timeout=10) as resp:
                version = parse_remote_version(resp.read().decode())
        except urllib.error.URLError as e:
            raise RemoteVersionUnavailableError(str(e)) from e
        if version is None:
            raise ValueError("no __version__ found in the remote file")
        return version

    def install_upgrade(self):
        env = self._config.base_env()
        env["UV_VENV_CLEAR"] = "1"
        subprocess.run(_INSTALL_CMD, check=True, env=env, timeout=300)

    def installed_version(self):
        try:
            result = subprocess.run(["lc", "--version"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        match = _SEMVER_RE.search(result.stdout)
        return match.group(1) if match else None
