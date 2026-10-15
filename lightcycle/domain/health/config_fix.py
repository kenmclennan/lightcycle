_FIXES = {
    "trusted-authors": (
        "it names the GitHub logins whose PR comments may drive a workflow; until it is set "
        "the pool reads none",
        "set `trusted-authors: <github-login> [<login> ...]` with `lc config --edit`",
    ),
    "workflows-remote": (
        "it is the remote the built-in workflow origin is pulled from",
        "set `workflows-remote: <git url>` with `lc config --edit`",
    ),
}


def blank_key_fix(key):
    does, how = _FIXES.get(key, (None, "set it with `lc config --edit`"))
    return "%s: %s" % (does, how) if does else how
