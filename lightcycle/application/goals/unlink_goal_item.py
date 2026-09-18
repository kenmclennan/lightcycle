from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_goal


class UnlinkGoalItemUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, goal_id, item_id):
        require_goal(self._store, goal_id)
        if item_id not in self._store.goal_items(goal_id):
            raise UseCaseError("%s is not linked to %s" % (item_id, goal_id))
        self._store.unlink_goal_item(goal_id, item_id)
