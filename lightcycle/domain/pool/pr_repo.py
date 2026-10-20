import re

_PR_URL_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/pull/\d+")


def pr_repo(pr):
    m = _PR_URL_RE.match(pr or "")
    if not m:
        return None
    return "%s/%s" % (m.group(1), m.group(2))
