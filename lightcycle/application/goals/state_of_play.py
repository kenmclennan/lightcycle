from lightcycle.application.errors import UseCaseError
from lightcycle.application.flow.engine_steps import GOAL_STATE_OF_PLAY_STEP, SUMMARY_ORIGIN_LABEL
from lightcycle.application.goals._common import require_goal
from lightcycle.application.work.item_partition import is_closed_item
from lightcycle.domain.goals import goal_log_stamp
from lightcycle.domain.work import State

_NONE = "(none)"


def _item_lines(refs):
    if not refs:
        return _NONE
    return "\n".join("%s - %s" % (i, t) if t else i for i, t in refs)


def assemble_goal_context(store, goal_id):
    goal = require_goal(store, goal_id)
    open_items, done_items = [], []
    for item_id in store.goal_items(goal_id):
        try:
            item = store.get_node(item_id)
        except KeyError:
            done_items.append((item_id, None))
            continue
        (done_items if is_closed_item(item) else open_items).append((item_id, item.title))
    entries = []
    for entry in reversed(store.goal_log(goal_id)):
        header = goal_log_stamp(entry.created_at)
        if entry.title:
            header = "%s  %s" % (header, entry.title)
        entries.append("%s\n%s" % (header, entry.body))
    return "\n\n".join([
        "Goal %s: %s\nStatus: %s    Project: %s"
        % (goal.id, goal.title, goal.status, goal.project or "(none)"),
        "## Description\n%s" % goal.description,
        "## Log (oldest first)\n%s" % ("\n\n".join(entries) if entries else _NONE),
        "## Open items\n%s" % _item_lines(open_items),
        "## Done items\n%s" % _item_lines(done_items),
    ])


class RefreshGoalStateOfPlayUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, goal_id):
        goal = require_goal(self._store, goal_id)
        self._refuse_when_in_flight(goal_id)
        if (
            not (goal.description or "").strip()
            and not self._store.goal_log(goal_id)
            and not self._store.goal_items(goal_id)
        ):
            raise UseCaseError("nothing to summarise for %s: no description, log or items" % goal_id)
        context = assemble_goal_context(self._store, goal_id)
        with self._store.transaction():
            item_id = self._store.create_item(
                "State of play: %s" % goal_id, context,
                shortcode=self._config.internal_shortcode())
            self._store.label_add(item_id, SUMMARY_ORIGIN_LABEL)
            step_id = self._store.create_step(
                step=GOAL_STATE_OF_PLAY_STEP, role="agent", parent=item_id)
            self._store.start_goal_state_of_play(goal_id, step_id)
        return step_id

    def _refuse_when_in_flight(self, goal_id):
        pointer = self._store.goal_state_of_play_step(goal_id)
        if not pointer:
            return
        try:
            node = self._store.get_node(pointer)
        except KeyError:
            return
        if node.state != State.DONE:
            raise UseCaseError(
                "a state of play refresh is already in flight for %s: %s" % (goal_id, pointer))
