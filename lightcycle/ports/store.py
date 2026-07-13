from abc import ABC, abstractmethod


class StorePort(ABC):
    @abstractmethod
    def item_artifacts(self, item_id):
        pass

    @abstractmethod
    def add_artifact(self, item_id, atype, value, label=None):
        pass

    @abstractmethod
    def replace_artifact(self, item_id, atype, value, label=None):
        pass

    @abstractmethod
    def all_nodes(self):
        pass

    @abstractmethod
    def all_steps(self):
        pass

    @abstractmethod
    def get_node(self, tid):
        pass

    @abstractmethod
    def node_view(self, tid):
        pass

    @abstractmethod
    def present_types(self, step):
        pass

    @abstractmethod
    def reassign(self, tid, role):
        pass

    @abstractmethod
    def route_to_human(self, tid, note):
        pass

    @abstractmethod
    def closed_items(self):
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
    def update_state(self, tid, state):
        pass

    @abstractmethod
    def assign(self, tid, assignee):
        pass

    @abstractmethod
    def dep_add(self, node_id, blocked_by):
        pass

    @abstractmethod
    def dep_remove(self, node_id, blocked_by):
        pass

    @abstractmethod
    def ready_steps(self):
        pass

    @abstractmethod
    def claim_ready(self, role):
        pass

    @abstractmethod
    def create_step(self, title, *, step=None, role=None, parent=None, deps=None,
                    project=None, goal=None, description=None, attention=False):
        pass

    @abstractmethod
    def edit_node(self, tid, *, title=None, description=None, goal=None, project=None,
                  parent=None, workflow=None) -> str:
        pass

    @abstractmethod
    def create_item(self, title, *, theme=None, project=None, goal=None, workflow=None):
        pass

    @abstractmethod
    def create_theme(self, title, *, project=None, goal=None, workflow=None):
        pass

    @abstractmethod
    def children(self, item_id):
        pass

    @abstractmethod
    def claimed_steps(self):
        pass

    @abstractmethod
    def history(self, tid):
        pass

    @abstractmethod
    def nodes_closed_since(self, since_date):
        pass

    @abstractmethod
    def last_n_closed_themes(self, n):
        pass


    @abstractmethod
    def closed_unretroed_items(self):
        pass

    @abstractmethod
    def last_n_closed_items(self, n):
        pass

    @abstractmethod
    def steps_at_step(self, step):
        pass

    @abstractmethod
    def delete(self, tid):
        pass
