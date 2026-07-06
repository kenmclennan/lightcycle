from abc import ABC, abstractmethod


class StorePort(ABC):
    @abstractmethod
    def story_artifacts(self, story_id):
        pass

    @abstractmethod
    def add_artifact(self, story_id, atype, value, label=None):
        pass

    @abstractmethod
    def all_tasks(self):
        pass

    @abstractmethod
    def get_task(self, tid):
        pass

    @abstractmethod
    def task_view(self, tid):
        pass

    @abstractmethod
    def present_types(self, task):
        pass

    @abstractmethod
    def reassign(self, tid, role):
        pass

    @abstractmethod
    def route_to_human(self, tid, note):
        pass

    @abstractmethod
    def closed_stories(self):
        pass

    @abstractmethod
    def ensure_store(self):
        pass

    @abstractmethod
    def reclaim(self, tid):
        pass

    @abstractmethod
    def note(self, tid, text):
        pass

    @abstractmethod
    def set_notes(self, tid, text):
        pass

    @abstractmethod
    def close(self, tid, reason):
        pass

    @abstractmethod
    def update_metadata(self, tid, meta):
        pass

    @abstractmethod
    def set_model(self, tid, model):
        pass

    @abstractmethod
    def label_add(self, tid, label):
        pass

    @abstractmethod
    def label_remove(self, tid, label):
        pass

    @abstractmethod
    def update_status(self, tid, status):
        pass

    @abstractmethod
    def assign(self, tid, assignee):
        pass

    @abstractmethod
    def dep_add(self, task_id, blocked_by):
        pass

    @abstractmethod
    def ready_tasks(self):
        pass

    @abstractmethod
    def claim_ready(self, role):
        pass

    @abstractmethod
    def create_task(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False):
        pass

    @abstractmethod
    def edit_task(self, tid, *, title=None, description=None, goal=None, project=None, parent=None):
        pass

    @abstractmethod
    def create_story(self, title, *, epic=None, project=None, goal=None, workflow=None):
        pass

    @abstractmethod
    def create_epic(self, title, *, project=None, goal=None, workflow=None):
        pass

    @abstractmethod
    def children(self, story_id):
        pass

    @abstractmethod
    def claimed_tasks(self):
        pass

    @abstractmethod
    def history(self, tid):
        pass

    @abstractmethod
    def tasks_closed_since(self, since_date):
        pass

    @abstractmethod
    def last_n_closed_epics(self, n):
        pass

    @abstractmethod
    def epics_closed_since(self, since_date_str):
        pass

    @abstractmethod
    def tasks_at_step(self, step):
        pass

    @abstractmethod
    def delete(self, tid):
        pass
