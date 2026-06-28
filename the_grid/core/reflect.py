import hashlib


def spec_hash_from_bytes(data):
    """First 8 hex chars of SHA-256 of spec file bytes."""
    return hashlib.sha256(data).hexdigest()[:8]


def build_reflection(task_id, feedback="", spec_hash="unknown"):
    """A reflection: a task id and freeform feedback text. The feedback is read
    and analysed by a human or an LLM, never parsed - what belongs in it is guided
    by the agent's step file, not codified here."""
    return {
        "task": task_id,
        "feedback": feedback or "",
        "spec_hash": spec_hash,
    }
