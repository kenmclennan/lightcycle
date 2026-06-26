"""Pure config-value resolution. Given a parsed config dict + the home dir."""
import os


def _expand(v, home):
    if v == "~":
        return home
    if v.startswith("~/"):
        return os.path.join(home, v[2:])
    return v


def cfg_path(cfg, key, default, home):
    v = cfg.get(key)
    if not v:
        return default
    v = _expand(v, home)
    return v if os.path.isabs(v) else os.path.join(home, v)


def projects_root(cfg, home):
    return cfg_path(cfg, "projects", os.path.join(home, "workspace", "projects"), home)


def specs_root(cfg, home):
    return cfg_path(cfg, "specs", os.path.join(home, "workspace", "specs"), home)


def branch_prefix(cfg, default="feat"):
    return cfg.get("branch-prefix") or cfg.get("branch_prefix") or default
