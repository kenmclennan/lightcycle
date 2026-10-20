import re

LC_MARKER = "<!-- lc -->"

_DECISION_RE = re.compile(r"<!-- lc:decision=(\w+) -->")


def thread_key(comment):
    return comment.in_reply_to_id or comment.id


def outstanding_threads(comments):
    latest = {}
    for c in sorted(comments, key=lambda c: c.created_at):
        if LC_MARKER in c.body:
            continue
        key = thread_key(c)
        if key is None:
            continue
        latest[key] = c
    return list(latest.values())


def review_has_signal(review):
    if review.state == "CHANGES_REQUESTED":
        return True
    if review.state == "COMMENTED":
        return bool(review.body.strip())
    return False


def outstanding_reviews(reviews, inline_comments, mention_token):
    linked = {c.review_id for c in inline_comments if c.review_id is not None}
    return [
        r for r in reviews
        if review_has_signal(r)
        and (
            (r.id is not None and r.id in linked)
            or (mention_token and mention_token in r.body)
        )
    ]


def parse_decision(body):
    m = _DECISION_RE.search(body)
    return m.group(1) if m else None
