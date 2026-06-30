def derive_signals(tasks, task_histories):
    """Compute objective signals from plain task records and their bd history sequences.

    tasks: list of task dicts (with 'id', 'step', 'outcome' keys)
    task_histories: dict mapping task_id -> list of bd history entries in bd's
                   natural order (newest-first), each {"Issue": {"status": ...}}

    Returns {"blocks": int, "review_rounds": int, "conflict": bool}.
    """
    review_rounds = sum(
        1 for t in tasks
        if t.step == "review" and t.outcome == "rejected"
    )
    conflict = any(
        t.step == "open-pr" and "conflict" in (t.outcome or "")
        for t in tasks
    )
    blocks = 0
    for t in tasks:
        if t.step != "build":
            continue
        history = task_histories.get(t.id, [])
        statuses = [h["Issue"]["status"] for h in reversed(history)]
        for i in range(len(statuses) - 1):
            if statuses[i] == "in_progress" and statuses[i + 1] == "open":
                blocks += 1
    return {"blocks": blocks, "review_rounds": review_rounds, "conflict": conflict}


def gather_feedback(reflections):
    """Collect the freeform feedback texts (with their task ids) for reading or LLM
    analysis. No counting or categorising - the raw text is the signal."""
    return [
        {"task": ref.task, "feedback": ref.feedback}
        for ref in reflections
        if (ref.feedback or "").strip()
    ]
