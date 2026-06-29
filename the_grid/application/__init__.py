"""Application layer: use cases (one action each, grouped by activity into folders).

A use case is a small class with injected port dependencies and a single
`execute(...)`. It holds the business logic that used to live in cli.py; cli is
left with parsing, dispatch, and rendering only.
"""
