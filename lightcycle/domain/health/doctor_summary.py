_PHRASES = {
    "store": ("store problem", "store problems"),
    "pins": ("item on an old workflow version", "items on an old workflow version"),
    "contract": ("workflow the engine rejects", "workflows the engine rejects"),
    "config": ("config problem", "config problems"),
    "orphans": ("item left behind", "items left behind"),
    "facets": ("facet problem", "facet problems"),
    "guidance": ("guidance problem", "guidance problems"),
}
_BEHIND = ("workflow out of date", "workflows out of date")
_WORKFLOW_OTHER = ("workflow problem", "workflow problems")


def _part(count, phrases):
    return "%d %s" % (count, phrases[0] if count == 1 else phrases[1])


def doctor_summary(problems) -> str:
    parts = []
    total = 0
    for category, findings in problems.items():
        if category == "github" or not findings:
            continue
        if category == "workflows":
            behind = sum(1 for p in findings if p.kind == "origin-behind")
            other = len(findings) - behind
            if behind:
                parts.append(_part(behind, _BEHIND))
            if other:
                parts.append(_part(other, _WORKFLOW_OTHER))
        else:
            parts.append(_part(len(findings), _PHRASES[category]))
        total += len(findings)
    if len(parts) >= 3:
        return "%d problems" % total
    return ", ".join(parts)
