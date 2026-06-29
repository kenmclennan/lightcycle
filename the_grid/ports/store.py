"""StorePort: the abstract task-store interface the application depends on."""
from abc import ABC, abstractmethod


class StorePort(ABC):

    @abstractmethod
    def story_artifacts(self, story_id):
        """Return the artifact list for a story."""

    @abstractmethod
    def add_artifact(self, story_id, atype, value, label=None):
        """Append an artifact entry to a story's metadata."""

    @abstractmethod
    def all_tasks(self):
        """Return all tasks as domain dicts."""

    @abstractmethod
    def get_task(self, tid):
        """Return one task as a domain dict."""

    @abstractmethod
    def task_view(self, tid):
        """Return a task dict enriched with its story's artifacts."""

    @abstractmethod
    def present_types(self, task):
        """Return the set of artifact types present on the task's story."""

    @abstractmethod
    def route_to_human(self, tid, note, role):
        """Re-route a task to the human queue with a note."""

    @abstractmethod
    def closed_stories(self):
        """Return closed stories shaped for core.worklog."""

    @abstractmethod
    def ensure_beads(self):
        """Initialise the bd store if not already present."""

    @abstractmethod
    def note(self, tid, text):
        """Add a freeform note to a task."""

    @abstractmethod
    def close(self, tid, reason):
        """Close a task with a reason string."""

    @abstractmethod
    def update_metadata(self, tid, meta):
        """Replace a task's metadata dict."""

    @abstractmethod
    def label_add(self, tid, label):
        """Add a label to a task."""

    @abstractmethod
    def label_remove(self, tid, label):
        """Remove a label from a task."""

    @abstractmethod
    def update_status(self, tid, status):
        """Set a task's status."""

    @abstractmethod
    def assign(self, tid, assignee):
        """Set (or clear) a task's assignee."""

    @abstractmethod
    def dep_add(self, task_id, blocked_by):
        """Record that task_id is blocked by blocked_by."""

    @abstractmethod
    def ready_beads(self):
        """Return all ready tasks as raw bead dicts."""

    @abstractmethod
    def claim_ready(self, role):
        """Atomically claim the next ready task for role. Returns a list (0 or 1 bead)."""

    @abstractmethod
    def create_task(self, title, *, step=None, role=None, parent=None, deps=None, labels=None):
        """Create a task bead and return its id.

        step and role, if given, are encoded as for:role and step:step labels.
        deps is a list of task ids this task depends on.
        labels is a list of extra label strings.
        """

    @abstractmethod
    def create_story(self, title, *, epic=None, labels=None):
        """Create a story bead and return its id.

        epic, if given, is the parent story id.
        labels is a list of label strings.
        """

    @abstractmethod
    def children(self, story_id):
        """Return child beads of a story as raw dicts."""

    @abstractmethod
    def list_beads_by_status(self, status):
        """Return all beads with the given status as raw dicts."""

    @abstractmethod
    def history(self, tid):
        """Return the raw history list for a task."""
