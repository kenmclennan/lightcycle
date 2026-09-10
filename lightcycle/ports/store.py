from abc import ABC, abstractmethod
from collections import namedtuple


ProjectEntry = namedtuple("ProjectEntry", "identity shortcode local_path remote")
ItemText = namedtuple("ItemText", "id title description notes")


class ProjectResolutionError(Exception):
    pass


class NodeNotFoundError(KeyError):
    def __str__(self):
        if self.args:
            return str(self.args[0])
        return super().__str__()


class StorePort(ABC):
    @abstractmethod
    def item_artifacts(self, item_id):
        pass

    @abstractmethod
    def add_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        pass

    @abstractmethod
    def replace_artifact(self, item_id, atype, value, label=None, internal=False, kind=None):
        pass

    @abstractmethod
    def all_nodes(self):
        pass

    @abstractmethod
    def all_items(self):
        pass

    @abstractmethod
    def all_nodes_including_done(self):
        pass

    @abstractmethod
    def item_texts(self):
        pass

    @abstractmethod
    def all_steps(self):
        pass

    @abstractmethod
    def all_steps_including_done(self):
        pass

    @abstractmethod
    def type_of(self, tid):
        pass

    @abstractmethod
    def get_item(self, tid):
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
    def snapshot_nodes(self):
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
    def note_condition(self, tid, text):
        pass

    @abstractmethod
    def set_notes(self, tid, text):
        pass

    @abstractmethod
    def reopen(self, tid):
        pass

    @abstractmethod
    def complete_node(self, tid, reason, disposition=None):
        pass

    @abstractmethod
    def complete_step_atomic(self, step, outcome, expected_assignee, next_step_spec):
        pass

    @abstractmethod
    def transaction(self):
        pass

    @abstractmethod
    def release(self):
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
    def labels_of(self, tid):
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
    def accrue_active_seconds(self, step_ids, seconds):
        pass

    @abstractmethod
    def record_usage(self, tid, input_tokens, output_tokens, cache_read_tokens,
                      cache_creation_tokens, cost_usd, cost_basis, thinking_tokens):
        pass

    @abstractmethod
    def record_attribution(self, tid, turn_count, tool_usage):
        pass

    @abstractmethod
    def tool_usage_for(self, step_id):
        pass

    @abstractmethod
    def usage_backfilled_logs(self):
        pass

    @abstractmethod
    def record_backfilled_usage(self, log_file, step_id, usage, attribution):
        pass

    @abstractmethod
    def record_live_usage(
        self, spawnid, log_file, offset, message_ids, pending_tool_use,
        posted_turn_count, posted_tool_usage, posted_input_tokens, posted_output_tokens,
        posted_cache_read_tokens, posted_cache_creation_tokens, posted_cost_usd,
        tid, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
        cost_usd, cost_basis, thinking_tokens, turn_count, tool_usage,
    ):
        pass

    @abstractmethod
    def usage_accrual_state(self, spawnid):
        pass

    @abstractmethod
    def clear_usage_accrual_state(self, spawnid):
        pass

    @abstractmethod
    def unclassified_backfill_logs(self):
        pass

    @abstractmethod
    def reclassify_backfilled_log(self, log_file, step_id, usage, attribution):
        pass

    @abstractmethod
    def logs_for_step(self, step_id):
        pass

    @abstractmethod
    def overwrite_usage_and_attribution(self, step_id, usage_totals, turn_count, tool_usage_totals):
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
    def create_item(self, title, description, *, project=None, goal=None, workflow=None,
                    shortcode=None):
        pass

    @abstractmethod
    def open_pass(self, item):
        pass

    @abstractmethod
    def current_pass(self, item):
        pass

    @abstractmethod
    def get_pass(self, pid):
        pass

    @abstractmethod
    def passes_of(self, item):
        pass

    @abstractmethod
    def close_pass(self, pid):
        pass

    @abstractmethod
    def open_run(self, item, pid, phase):
        pass

    @abstractmethod
    def get_run(self, rid):
        pass

    @abstractmethod
    def current_run(self, item, phase):
        pass

    @abstractmethod
    def runs_of(self, item, pid=None):
        pass

    @abstractmethod
    def open_runs_of(self, item, pid=None):
        pass

    @abstractmethod
    def set_branch(self, rid, branch):
        pass

    @abstractmethod
    def set_pr(self, rid, pr):
        pass

    @abstractmethod
    def set_content_pin(self, rid, content_pin):
        pass

    @abstractmethod
    def record_pr_pin(self, rid, pr, content_pin):
        pass

    @abstractmethod
    def set_comments_dispatched_through(self, rid, value):
        pass

    @abstractmethod
    def set_comments_handled_through(self, rid, value):
        pass

    @abstractmethod
    def close_run(self, rid, state="merged"):
        pass

    @abstractmethod
    def set_watched_step(self, tid, watched):
        pass

    @abstractmethod
    def set_step_pass(self, tid, pid):
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
    def closed_unretroed_items(self):
        pass

    @abstractmethod
    def closed_unretroed_passes(self):
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

    @abstractmethod
    def add_project(self, identity, *, shortcode=None, local_path=None, remote=None):
        pass

    @abstractmethod
    def get_project(self, identity):
        pass

    @abstractmethod
    def list_projects(self):
        pass

    @abstractmethod
    def remove_project(self, identity):
        pass

    @abstractmethod
    def find_project(self, ref):
        pass

    @abstractmethod
    def resolve_project_path(self, ref):
        pass
