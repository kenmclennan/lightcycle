import shlex
import subprocess
import sys
import urllib.parse
import webbrowser

from lightcycle.adapters.process_group import run_in_group
from lightcycle.ports.launcher import LauncherPort


def _os_open_command():
    return "open" if sys.platform == "darwin" else "xdg-open"


def open_path(path):
    try:
        result = run_in_group(
            [_os_open_command(), path], capture_output=True, check=False, timeout=10
        )
    except Exception:
        return False
    return result.returncode == 0


def open_url(url):
    if urllib.parse.urlparse(url).scheme.lower() not in ("http", "https"):
        return open_path(url)
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def edit(editor, path):
    result = subprocess.run(shlex.split(editor) + [path], timeout=None)
    return result.returncode


def edit_detached(editor, path):
    subprocess.Popen(
        shlex.split(editor) + [path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class LauncherAdapter(LauncherPort):
    def open_url(self, url):
        return open_url(url)

    def open_path(self, path):
        return open_path(path)

    def edit(self, editor, path):
        return edit(editor, path)

    def edit_detached(self, editor, path):
        return edit_detached(editor, path)
