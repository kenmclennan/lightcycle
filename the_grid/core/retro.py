import collections


def derive_signals(tasks, task_histories):
    """Compute objective signals from plain task records and their bd history sequences.

    tasks: list of task dicts (with 'id', 'step', 'outcome' keys)
    task_histories: dict mapping task_id -> list of bd history entries in bd's
                   natural order (newest-first), each {"Issue": {"status": ...}}

    Returns {"blocks": int, "review_rounds": int, "conflict": bool}.
    """
    review_rounds = sum(
        1 for t in tasks
        if t.get("step") == "review" and t.get("outcome") == "rejected"
    )
    conflict = any(
        t.get("step") == "open-pr" and "conflict" in (t.get("outcome") or "")
        for t in tasks
    )
    blocks = 0
    for t in tasks:
        if t.get("step") != "build":
            continue
        history = task_histories.get(t["id"], [])
        statuses = [h["Issue"]["status"] for h in reversed(history)]
        for i in range(len(statuses) - 1):
            if statuses[i] == "in_progress" and statuses[i + 1] == "open":
                blocks += 1
    return {"blocks": blocks, "review_rounds": review_rounds, "conflict": conflict}


def aggregate_reflections(reflections):
    """Aggregate a list of parsed reflection dicts into section counts and frequency maps.

    Returns:
        {
            "section_counts": {section: {"used": int, "skipped": int, "guess": int}},
            "missing_counts": Counter,
            "noise_counts": Counter,
        }
    """
    section_counts = {}
    for ref in reflections:
        for sec, verdict in (ref.get("sections") or {}).items():
            if sec not in section_counts:
                section_counts[sec] = {"used": 0, "skipped": 0, "guess": 0}
            if verdict in section_counts[sec]:
                section_counts[sec][verdict] += 1
    missing_counts = collections.Counter(
        m for ref in reflections for m in (ref.get("missing") or [])
    )
    noise_counts = collections.Counter(
        item for ref in reflections for item in (ref.get("noise") or [])
    )
    return {
        "section_counts": section_counts,
        "missing_counts": missing_counts,
        "noise_counts": noise_counts,
    }
