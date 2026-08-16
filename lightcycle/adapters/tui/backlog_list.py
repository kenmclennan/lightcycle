from dataclasses import dataclass

from lightcycle.application.work.project_of import short_project_label


@dataclass(frozen=True)
class BacklogRow:
    id: str
    project: str
    title: str


def build_backlog_rows(human_node_rows):
    return [
        BacklogRow(id=r.step.id, project=short_project_label(r.project), title=r.step.title)
        for r in human_node_rows
    ]
