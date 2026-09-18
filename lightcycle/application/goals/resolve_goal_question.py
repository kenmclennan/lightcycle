from lightcycle.application.errors import UseCaseError
from lightcycle.application.goals._common import require_text


class ResolveGoalQuestionUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, question_id, resolution):
        question = self._store.get_goal_question(question_id)
        if question is None:
            raise UseCaseError("no such question: #%s" % question_id)
        if question.resolved_at is not None:
            raise UseCaseError("question #%s is already resolved" % question_id)
        resolution = require_text(resolution, "resolution")
        with self._store.transaction():
            self._store.resolve_goal_question(question_id, resolution)
            self._store.add_goal_log(
                question.goal_id, "Resolved: %s - %s" % (question.body, resolution)
            )
