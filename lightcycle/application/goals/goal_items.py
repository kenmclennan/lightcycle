from collections import namedtuple

from lightcycle.application.goals._common import require_goal
from lightcycle.application.goals.show_goal import GoalItemRef
from lightcycle.application.work.item_filter import text_matches
from lightcycle.application.work.item_partition import is_backlogged_item, is_closed_item
from lightcycle.application.work.priority_rows import PrioritySelection, select_priority_rows
from lightcycle.application.work.status import StatusUseCase

GoalItems = namedtuple("GoalItems", "total selection stepless backlog done")


class GoalItemsUseCase:
    def __init__(self, store, flow_service):
        self._store = store
        self._flow_service = flow_service

    def execute(self, goal_id, text=None):
        require_goal(self._store, goal_id)
        item_ids = self._store.goal_items(goal_id)
        lanes = StatusUseCase(self._store).execute().lanes
        selection = select_priority_rows(self._store, lanes, self._flow_service)
        selected_ids = {
            row.owning_node.id for row in selection.attention + selection.active + selection.queued
        }
        linked = set(item_ids)
        stepless, backlog, done = [], [], []
        for item_id in item_ids:
            try:
                item = self._store.get_node(item_id)
            except KeyError:
                if not text or text.lower() in item_id.lower():
                    done.append(GoalItemRef(item_id, None))
                continue
            if not text_matches(item, text):
                continue
            ref = GoalItemRef(item_id, item.title)
            if is_closed_item(item):
                done.append(ref)
            elif item_id in selected_ids:
                continue
            elif is_backlogged_item(self._store, item):
                backlog.append(ref)
            else:
                stepless.append(ref)
        return GoalItems(
            total=len(item_ids),
            selection=self._filter(selection, linked, text),
            stepless=stepless,
            backlog=backlog,
            done=done,
        )

    def _filter(self, selection, linked, text):
        def keep(rows):
            return [
                r for r in rows
                if r.owning_node.id in linked and text_matches(r.owning_node, text)
            ]

        return PrioritySelection(
            attention=keep(selection.attention),
            active=keep(selection.active),
            queued=keep(selection.queued),
        )
