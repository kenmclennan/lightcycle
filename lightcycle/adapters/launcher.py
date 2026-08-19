import subprocess
import sys
import webbrowser

from lightcycle.ports.launcher import LauncherPort


def _os_open_command():
    return "open" if sys.platform == "darwin" else "xdg-open"


def open_url(url):
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def open_path(path):
    try:
        result = subprocess.run(
            [_os_open_command(), path], capture_output=True, check=False
        )
    except Exception:
        return False
    return result.returncode == 0


class LauncherAdapter(LauncherPort):
    def open_url(self, url):
        return open_url(url)

    def open_path(self, path):
        return open_path(path)
