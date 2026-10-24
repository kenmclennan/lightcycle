from lightcycle.application.errors import UseCaseError
from lightcycle.domain.feedback.review_yield import CAUSED_BY, FOUND_BY, found_by_problem


class LinkSourceUseCase:
    def __init__(self, store):
        self._store = store

    def check(self, caused_by, found_by, item=None):
        for target in caused_by or []:
            self._check_target(target, item)
        if found_by is not None:
            problem = found_by_problem(found_by)
            if problem:
                raise UseCaseError("--found-by %r: %s" % (found_by, problem))

    def execute(self, item, caused_by, found_by, unset=()):
        self.check(caused_by, found_by, item)
        if caused_by is not None or CAUSED_BY in unset:
            self._store.remove_artifact(item, CAUSED_BY)
        for target in dict.fromkeys(caused_by or []):
            self._store.add_artifact(item, CAUSED_BY, target, internal=True)
        if found_by is not None or FOUND_BY in unset:
            self._store.remove_artifact(item, FOUND_BY)
        if found_by is not None:
            self._store.add_artifact(item, FOUND_BY, found_by, internal=True)

    def _check_target(self, target, item):
        node_type = self._store.type_of(target)
        if node_type is None:
            raise UseCaseError("--caused-by: unknown node '%s'" % target)
        if node_type != "item":
            owner = self._store.get_node(target).item
            raise UseCaseError(
                "--caused-by: '%s' is a step, not an item; name its item '%s'" % (target, owner))
        if item is not None and target == item:
            raise UseCaseError("--caused-by: '%s' cannot be caused by itself" % item)
