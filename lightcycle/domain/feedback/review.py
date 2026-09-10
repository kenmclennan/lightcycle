LC_MARKER = "<!-- lc -->"


def is_bot(author):
    return "[bot]" in author


def eligible(author, allowlist):
    return not is_bot(author) or author in allowlist


def thread_key(comment):
    return comment.in_reply_to_id or comment.id


def outstanding_threads(comments):
    marked_threads = {thread_key(c) for c in comments if LC_MARKER in c.body}
    latest = {}
    for c in sorted(comments, key=lambda c: c.created_at):
        if LC_MARKER in c.body:
            continue
        key = thread_key(c)
        if key is None or key in marked_threads:
            continue
        latest[key] = c
    return list(latest.values())


def review_has_signal(review):
    if review.state == "CHANGES_REQUESTED":
        return True
    if review.state == "COMMENTED":
        return bool(review.body.strip())
    return False


def outstanding_reviews(reviews, comments):
    marked_at = sorted(c.created_at for c in comments if LC_MARKER in c.body)
    outstanding = []
    for r in reviews:
        if not review_has_signal(r):
            continue
        if LC_MARKER in r.body:
            continue
        if any(ts > r.created_at for ts in marked_at):
            continue
        outstanding.append(r)
    return outstanding
