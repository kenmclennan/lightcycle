from lightcycle.application.errors import UseCaseError


def require_git_identity(git, path, error=UseCaseError):
    missing = git.missing_identity(path)
    if not missing:
        return
    fixes = " and ".join(
        'git config --global %s "<%s>"' % (key, key.split(".")[1]) for key in missing
    )
    raise error(
        "git has no %s configured, so the initial commit at %s cannot be made - run %s, then retry"
        % (" or ".join(missing), path, fixes)
    )
