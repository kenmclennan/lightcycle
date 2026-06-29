"""FsPort: the abstract filesystem/config interface the application depends on.

Phase 2 splits the config concerns out into a dedicated Config object; for now
they ride along here as the single filesystem-facing port.
"""
from abc import ABC, abstractmethod


class FsPort(ABC):

    @abstractmethod
    def grid_root(self):
        """Return the engine's root directory."""

    @abstractmethod
    def config_path(self):
        """Return the path to the config file."""

    @abstractmethod
    def load_config(self):
        """Load and return the config dict."""

    @abstractmethod
    def ensure_config(self):
        """Create the config file if missing; return the config dict."""

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
