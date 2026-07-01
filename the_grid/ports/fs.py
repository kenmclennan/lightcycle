"""FsPort: reading step files and well-known dirs under the engine root.

The engine root and the config file are owned by Config (the environment
boundary); this port is only the filesystem reads rooted at it.
"""
from abc import ABC, abstractmethod


class FsPort(ABC):

    @abstractmethod
    def step_roles(self):
        """Return the available step roles."""

    @abstractmethod
    def read_md(self, relpath):
        """Read a markdown file relative to the engine root."""

    @abstractmethod
    def parse_step(self, role):
        """Parse and return the step definition for role."""

    @abstractmethod
    def worktrees_dir(self):
        """Return the directory worktrees are created under."""

    @abstractmethod
    def store_ready(self):
        """Return True if the task store is initialised."""

    @abstractmethod
    def read_bytes(self, path):
        """Read a file's bytes at an absolute path, or None if it does not exist."""

    @abstractmethod
    def list_dir(self, path):
        """Return the sorted names of the subdirectories of path."""

    @abstractmethod
    def ensure_logs_dir(self):
        """Create the engine's logs dir if absent; return its path."""

    @abstractmethod
    def ensure_worktrees_ignored(self):
        """Ensure `.worktrees/` is gitignored at the engine root (idempotent)."""
