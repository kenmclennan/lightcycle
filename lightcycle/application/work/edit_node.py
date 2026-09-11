from dataclasses import dataclass
from typing import Optional

from lightcycle.application.errors import UseCaseError
from lightcycle.application.work.title_guard import validate_title
from lightcycle.domain.work import refuse_fields, render_field_refusal

_EDIT_FIELDS = ("title", "description", "project", "workflow", "label", "notes")


@dataclass(frozen=True)
class EditNodeInput:
    step: str
    title: Optional[str] = None
    description: Optional[str] = None
    project: Optional[str] = None
    workflow: Optional[str] = None
    label: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class EditNodeResponse:
    id: str


class EditNodeUseCase:
    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, input: EditNodeInput) -> EditNodeResponse:
        validate_title(self._config, input.title)
        given = {f for f in _EDIT_FIELDS if getattr(input, f) is not None}
        refusal = refuse_fields(self._store.type_of(input.step), given)
        if refusal is not None:
            raise UseCaseError(render_field_refusal(refusal))
        with self._store.transaction():
            tid = self._store.edit_node(
                input.step,
                title=input.title,
                description=input.description,
                project=input.project,
                workflow=input.workflow,
            )
            if input.label:
                self._store.label_add(tid, input.label)
            if input.notes is not None:
                self._store.set_notes(tid, input.notes)
        return EditNodeResponse(id=tid)
