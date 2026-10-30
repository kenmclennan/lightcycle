import contextlib
import os
import shutil
import sys
import tempfile

REAL_HOME_ENV = "LC_TEST_REAL_HOME"

REAL_HOME = os.environ.get(REAL_HOME_ENV) or os.path.realpath(os.path.expanduser("~"))
os.environ[REAL_HOME_ENV] = REAL_HOME

_REPO_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))

_SIBLING_CHECKOUTS = ("lightcycle-workflows",)

_GIT_IDENTITY_VARS = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "EMAIL",
    "GIT_CONFIG",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
)

_GIT_CONFIG_INDEXED = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")

_PATH_EVENTS = {
    "open": 1,
    "os.mkdir": 1,
    "os.listdir": 1,
    "os.scandir": 1,
    "os.remove": 1,
    "os.rename": 2,
    "os.rmdir": 1,
    "shutil.copyfile": 2,
    "shutil.copytree": 2,
    "shutil.rmtree": 1,
}

_GITCONFIG_TEXT = "[user]\n\tuseConfigOnly = true\n"


class RealHomeAccessError(Exception):
    pass


class _State:
    armed = False
    installed = False
    violations = []
    fake_home = None


def _sibling_checkouts():
    found = []
    base = _REPO_ROOT
    while True:
        base = os.path.dirname(base)
        for name in _SIBLING_CHECKOUTS:
            candidate = os.path.join(base, name)
            if os.path.isdir(candidate):
                found.append(candidate)
        if base == os.path.dirname(base):
            return found


def _allowed_roots():
    roots = [
        _REPO_ROOT,
        sys.prefix,
        sys.exec_prefix,
        sys.base_prefix,
        sys.base_exec_prefix,
        tempfile.gettempdir(),
    ]
    roots.extend(entry for entry in sys.path if entry)
    roots.extend(_sibling_checkouts())
    return [os.path.realpath(root) for root in roots]


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _is_violation(raw):
    if not isinstance(raw, (str, bytes, os.PathLike)):
        return None
    try:
        path = os.fsdecode(raw)
    except TypeError:
        return None
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not path.startswith(REAL_HOME) or not _inside(path, REAL_HOME):
        return None
    if any(_inside(path, root) for root in _allowed_roots()):
        return None
    return path


def _hook(event, args):
    if not _State.armed:
        return
    count = _PATH_EVENTS.get(event)
    if count is None:
        return
    for raw in args[:count]:
        path = _is_violation(raw)
        if path is not None:
            _State.violations.append((event, path))
            raise RealHomeAccessError("%s touched the real home: %s" % (event, path))


def install_guard():
    if _State.installed:
        return
    sys.addaudithook(_hook)
    _State.installed = True


def begin_test():
    install_guard()
    _State.violations = []
    _State.armed = True


def end_test():
    _State.armed = False
    violations, _State.violations = _State.violations, []
    if _State.fake_home:
        shutil.rmtree(_State.fake_home, ignore_errors=True)
        _State.fake_home = None
    if violations:
        raise AssertionError(
            "test touched the real home: "
            + "; ".join("%s %s" % violation for violation in violations)
        )


@contextlib.contextmanager
def expect_real_home_access():
    mark = len(_State.violations)
    absorbed = []
    try:
        yield absorbed
    finally:
        absorbed.extend(_State.violations[mark:])
        del _State.violations[mark:]


def cleanup():
    if _State.fake_home:
        shutil.rmtree(_State.fake_home, ignore_errors=True)
        _State.fake_home = None


def apply():
    if _State.fake_home:
        shutil.rmtree(_State.fake_home, ignore_errors=True)
    home = tempfile.mkdtemp(prefix="lc-test-userhome-")
    _State.fake_home = home
    gitconfig = os.path.join(home, ".gitconfig-hermetic")
    with open(gitconfig, "w") as handle:
        handle.write(_GITCONFIG_TEXT)
    os.environ[REAL_HOME_ENV] = REAL_HOME
    os.environ["HOME"] = home
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    os.environ["GIT_CONFIG_GLOBAL"] = gitconfig
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    for var in _GIT_IDENTITY_VARS:
        os.environ.pop(var, None)
    for var in [v for v in os.environ if v.startswith(_GIT_CONFIG_INDEXED)]:
        del os.environ[var]
    return home
