import hashlib


def _split_csv(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def build_sections(used="", skipped="", guess=""):
    """Build a sections dict from comma-separated section name strings."""
    sections = {}
    for name in _split_csv(used):
        sections[name] = "used"
    for name in _split_csv(skipped):
        sections[name] = "skipped"
    for name in _split_csv(guess):
        sections[name] = "guess"
    return sections


def spec_hash_from_bytes(data):
    """First 8 hex chars of SHA-256 of spec file bytes."""
    return hashlib.sha256(data).hexdigest()[:8]


def build_reflection(task_id, used="", skipped="", guess="",
                     missing=None, noise=None, friction=None, spec_hash="unknown"):
    """Assemble the reflection artifact dict from parsed CLI inputs."""
    return {
        "task": task_id,
        "sections": build_sections(used, skipped, guess),
        "missing": list(missing) if missing else [],
        "noise": list(noise) if noise else [],
        "friction": list(friction) if friction else [],
        "spec_hash": spec_hash,
    }
