from dataclasses import dataclass
from typing import List, Tuple

from lightcycle.application.work.item_filter import project_matches
from lightcycle.application.work.project_of import project_of
from lightcycle.domain.work import ProjectIdentity


@dataclass(frozen=True)
class ProjectCount:
    project: str
    count: int


def project_counts(store, items) -> Tuple[List[ProjectCount], int]:
    projects = [
        ProjectCount(
            project=ProjectIdentity.short_name(p.identity),
            count=sum(
                1 for t in items
                if project_matches(store, t, ProjectIdentity.short_name(p.identity))
            ),
        )
        for p in store.list_projects()
    ]
    unscoped = sum(1 for t in items if project_of(store, t) is None)
    return projects, unscoped
