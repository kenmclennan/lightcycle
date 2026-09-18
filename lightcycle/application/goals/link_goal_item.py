from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_goal


class LinkGoalItemUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, goal_id, item_id):
        require_goal(self._store, goal_id)
        if self._store.type_of(item_id) != "item":
            raise UseCaseError("%s is not an item" % item_id)
        if item_id in self._store.goal_items(goal_id):
            raise UseCaseError("%s is already linked to %s" % (item_id, goal_id))
        self._store.link_goal_item(goal_id, item_id)
