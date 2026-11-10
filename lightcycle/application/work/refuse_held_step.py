from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.held_steps import HeldSteps


class RefuseHeldStepUseCase:
    def __init__(self, store, workers):
        self._held = HeldSteps(store, workers)

    def execute(self, item):
        held = self._held.of_item(item)
        if held:
            raise UseCaseError(
                "a worker is running %s - lc halt %s first"
                % (", ".join(step.id for step, _ in held), item)
            )
