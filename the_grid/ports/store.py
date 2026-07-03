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
        """Return a TaskView - the task plus its story's artifacts."""

    @abstractmethod
    def present_types(self, task):
        """Return the set of artifact types present on the task's story."""

    @abstractmethod
    def reassign(self, tid, role):
        """Make the task owned by role and reset it to ready (open, unclaimed)."""

    @abstractmethod
    def route_to_human(self, tid, note):
        """Re-route a task to the human queue with a note."""

    @abstractmethod
    def closed_stories(self):
        """Return closed stories shaped for core.worklog."""

    @abstractmethod
    def ensure_store(self):
        """Initialise the task store if not already present."""

    @abstractmethod
    def reclaim(self, tid):
        """Release a task's claim - reset it to ready (open, unclaimed)."""

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
    def ready_tasks(self):
        """Return all ready tasks as Task entities."""

    @abstractmethod
    def claim_ready(self, role):
        """Atomically claim the next ready task for role. Returns a Task, or None."""

    @abstractmethod
    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None):
        """Create a task and return its id.

        role/step/project/goal are structured attributes; the adapter encodes them
        (the application does not build label strings). deps is a list of task ids
        this task depends on.
        """

    @abstractmethod
    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
        """Update an existing task's fields. Only the given (non-None) fields change."""

    @abstractmethod
    def create_story(self, title, *, epic=None, project=None, goal=None):
        """Create a story and return its id.

        epic, if given, is the parent story id. project/goal are structured
        attributes the adapter encodes.
        """

    @abstractmethod
    def children(self, story_id):
        """Return the child tasks of a story as Task entities."""

    @abstractmethod
    def claimed_tasks(self):
        """Return the tasks currently claimed by a worker (each carries claimed_by)."""

    @abstractmethod
    def history(self, tid):
        """Return the raw history list for a task."""

    @abstractmethod
    def tasks_closed_since(self, since_date):
        """Return all tasks (not stories) closed on/after since_date (YYYY-MM-DD string)."""

    @abstractmethod
    def last_n_closed_epics(self, n):
        """Return the last N closed top-level stories (epics), ordered by closed_at descending."""
