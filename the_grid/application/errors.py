"""Application-layer errors.

A use case raises UseCaseError when it cannot proceed for a domain reason (an
invalid transition, a missing required artifact, nothing to unblock). cli
catches it at the command edge, writes the message to stderr, and returns 1 -
keeping the IO (stderr, exit codes) out of the use case.
"""


class UseCaseError(Exception):
    """A use case cannot proceed; the message is human-facing."""
