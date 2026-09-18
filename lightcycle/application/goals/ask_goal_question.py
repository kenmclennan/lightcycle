from lightcycle.application.goals._common import require_goal, require_text


class AskGoalQuestionUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, goal_id, body):
        require_goal(self._store, goal_id)
        return self._store.add_goal_question(goal_id, require_text(body, "question"))
