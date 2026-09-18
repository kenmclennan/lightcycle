from collections import namedtuple

from lightcycle.application.goals._common import require_goal

GoalItemRef = namedtuple("GoalItemRef", "id title")
GoalView = namedtuple("GoalView", "goal log questions items")


class ShowGoalUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, goal_id):
        goal = require_goal(self._store, goal_id)
        items = []
        for item_id in self._store.goal_items(goal_id):
            try:
                title = self._store.get_node(item_id).title
            except KeyError:
                title = None
            items.append(GoalItemRef(item_id, title))
        return GoalView(
            goal=goal,
            log=self._store.goal_log(goal_id),
            questions=self._store.goal_questions(goal_id),
            items=items,
        )
