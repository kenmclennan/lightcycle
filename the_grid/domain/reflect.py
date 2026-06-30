import hashlib

from the_grid.domain.reflection import Reflection


def spec_hash_from_bytes(data):
    """First 8 hex chars of SHA-256 of spec file bytes."""
    return hashlib.sha256(data).hexdigest()[:8]


def build_reflection(task_id, feedback="", spec_hash="unknown") -> Reflection:
    return Reflection(task=task_id, feedback=feedback or "", spec_hash=spec_hash)
