import os
import shutil
import sys
from pathlib import Path

_TOP = (0, 255, 255)
_BOT = (45, 90, 255)
_RESET = "\033[0m"


def _banner_text():
    return (Path(__file__).resolve().parent / "banner.txt").read_text()


def render_banner(text, color=True, width=None):
    lines = text.rstrip("\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    block = max((len(line) for line in lines), default=0)
    if width is not None and block > width:
        start = (block - width) // 2
        lines = [line[start:start + width] for line in lines]
    if not color:
        return "\n".join(lines)
    span = max(len(lines) - 1, 1)
    out = []
    for i, line in enumerate(lines):
        t = i / span
        r = int(_TOP[0] + (_BOT[0] - _TOP[0]) * t)
        g = int(_TOP[1] + (_BOT[1] - _TOP[1]) * t)
        b = int(_TOP[2] + (_BOT[2] - _TOP[2]) * t)
        out.append("\033[1;38;2;%d;%d;%dm%s%s" % (r, g, b, line, _RESET))
    return "\n".join(out)


def _color_enabled(stream, env):
    if env.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _fit_width(stream):
    if not getattr(stream, "isatty", lambda: False)():
        return None
    return shutil.get_terminal_size().columns


def show_banner(stream=None, env=None):
    stream = stream if stream is not None else sys.stdout
    env = env if env is not None else os.environ
    stream.write("\n")
    stream.write(render_banner(
        _banner_text(), color=_color_enabled(stream, env), width=_fit_width(stream)
    ))
    stream.write("\n\n")
