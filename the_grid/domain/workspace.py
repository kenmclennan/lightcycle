"""Pure workspace decisions: branch naming, worktree path, repo selection."""
import os
import re


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def branch_for(feature, prefix="feat"):
    return "%s/%s" % (prefix, slugify(feature))


def worktree_path(worktrees_dir, story):
    return os.path.join(worktrees_dir, story)


def story_repo(artifacts, default):
    """The single repo name a story builds (its `repo` artifact), else `default`."""
    for a in artifacts:
        if a.type == "repo":
            return a.value
    return default


def is_worktree_lock_error(text):
    """True when a `git worktree add` failure is transient lock contention from a
    concurrent peer (worth retrying), not a real error. Several agents creating
    worktrees against one target repo at once race on git's `.git/worktrees` lock."""
    t = (text or "").lower()
    return ("could not lock" in t or "already locked" in t
            or "index.lock" in t or ".lock': file exists" in t)
