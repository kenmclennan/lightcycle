"""Pure workspace decisions: branch naming, worktree path, repo selection."""
import os


def branch_for(story):
    return "grid/%s" % story


def worktree_path(worktrees_dir, story):
    return os.path.join(worktrees_dir, story)


def story_repo(artifacts, default):
    """The single repo name a story builds (its `repo` artifact), else `default`."""
    for a in artifacts:
        if a.get("type") == "repo":
            return a["value"]
    return default
