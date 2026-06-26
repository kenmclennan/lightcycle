"""Filesystem + config IO: grid root, config file, agent files, well-known dirs."""
import os
from pathlib import Path

from the_grid.core import agents as core_agents


def grid_root():
    override = os.environ.get("GRID_ROOT_OVERRIDE")
    if override:
        return override
    return str(Path(__file__).resolve().parents[2])


def config_path():
    override = os.environ.get("GRID_CONFIG")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "the-grid", "config")


def load_config():
    p = config_path()
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return core_agents.parse_frontmatter(f.read())


def _default_config_text():
    return "projects: ~/workspace/projects\nspecs: ~/workspace/specs\n"


def ensure_config():
    """Seed the default config file if absent. Returns True if it was created."""
    p = config_path()
    if os.path.exists(p):
        return False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(_default_config_text())
    return True


def agent_roles():
    adir = os.path.join(grid_root(), "agents")
    if not os.path.isdir(adir):
        return []
    return sorted(f[:-3] for f in os.listdir(adir) if f.endswith(".md"))


def read_md(relpath):
    """Read a markdown file under the grid root; return {meta, body, path} or None."""
    path = os.path.join(grid_root(), relpath)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        text = f.read()
    meta, body = core_agents.split_frontmatter(text)
    return {"meta": meta, "body": body, "path": path}


def parse_agent(role):
    """Read a flow agent file agents/<role>.md; return {meta, body, path} or None."""
    return read_md(os.path.join("agents", "%s.md" % role))


def worktrees_dir():
    return os.path.join(grid_root(), ".worktrees")


def store_ready():
    return os.path.isdir(os.path.join(grid_root(), ".beads"))
