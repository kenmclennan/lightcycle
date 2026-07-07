from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AddItemInput:
    title: str
    goal: Optional[str] = None
    project: Optional[str] = None
    description: Optional[str] = None
    attention: bool = False


@dataclass(frozen=True)
class AddItemResponse:
    step: str


class AddItemUseCase:
    def __init__(self, store):
        self._store = store

    def execute(self, input: AddItemInput) -> AddItemResponse:
        return AddItemResponse(step=self._store.create_step(
            input.title, role="human", project=input.project, goal=input.goal,
            description=input.description, attention=input.attention))
