from dataclasses import dataclass

from lightcycle.application.work.activate_item import ActivateItemInput, ActivateItemUseCase

_CARRIED_ARTIFACT_TYPES = ("spec", "repo")


@dataclass(frozen=True)
class FileChildItemInput:
    parent: str
    workflow: str
    step: str


@dataclass(frozen=True)
class FileChildItemResponse:
    item: str
    step: str


class FileChildItemUseCase:
    def __init__(self, store, flow):
        self._store = store
        self._activate = ActivateItemUseCase(store, flow)

    def execute(self, input: FileChildItemInput) -> FileChildItemResponse:
        parent = self._store.get_node(input.parent)
        child = self._store.create_item(
            parent.title, theme=parent.theme, project=parent.project, workflow=input.workflow
        )
        self._store.add_artifact(child, "filed-from", input.parent)
        for artifact in self._store.item_artifacts(input.parent):
            if artifact.type in _CARRIED_ARTIFACT_TYPES:
                self._store.add_artifact(child, artifact.type, artifact.value, artifact.label)
        response = self._activate.execute(
            ActivateItemInput(item=child, workflow=input.workflow, step=input.step)
        )
        return FileChildItemResponse(item=child, step=response.step)
