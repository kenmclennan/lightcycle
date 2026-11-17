_PHRASES = {
    "store": ("store problem", "store problems"),
    "pins": ("item on an old workflow version", "items on an old workflow version"),
    "contract": ("workflow the engine rejects", "workflows the engine rejects"),
    "config": ("config problem", "config problems"),
    "orphans": ("worktree with stray processes", "worktrees with stray processes"),
    "teardown": ("item close refused", "item closes refused"),
    "facets": ("facet problem", "facet problems"),
    "guidance": ("guidance problem", "guidance problems"),
    "workflows": ("workflow problem", "workflow problems"),
}


def _part(count, phrases):
    return "%d %s" % (count, phrases[0] if count == 1 else phrases[1])


def doctor_summary(problems) -> str:
    parts = []
    total = 0
    for category, findings in problems.items():
        if category == "github" or not findings:
            continue
        parts.append(_part(
            len(findings),
            _PHRASES.get(category, ("%s problem" % category, "%s problems" % category)),
        ))
        total += len(findings)
    if len(parts) >= 3:
        return "%d problems" % total
    return ", ".join(parts)
