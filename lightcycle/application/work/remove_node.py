from dataclasses import dataclass

from lightcycle.application.errors import UseCaseError
from lightcycle.domain.pool import WorkerPool

_STRUCTURAL_TYPES = ("item", "theme")


@dataclass(frozen=True)
class RemoveNodeInput:
    id: str
    force: bool = False


@dataclass(frozen=True)
class RemoveNodeResponse:
    id: str
    steps_removed: int
    worktree_removed: bool


class RemoveNodeUseCase:
    def __init__(self, store, workers, worktrees, git):
        self._store = store
        self._workers = workers
        self._worktrees = worktrees
        self._git = git

    def _live_step(self, step_ids):
        if not step_ids:
            return None
        covered = WorkerPool.from_state(self._workers.workers_state()).covered_steps(
            self._workers.pid_alive
        )
        for t in self._store.claimed_steps():
            if t.id in step_ids and t.id in covered:
                return t.id
        return None

    def _worktree_dirty(self, node_id):
        target = self._worktrees.target_repo(node_id)
        path = self._worktrees.worktree_path(node_id)
        return self._git.worktree_registered(target, path) and self._git.has_uncommitted(path)

    def execute(self, input: RemoveNodeInput) -> RemoveNodeResponse:
        try:
            node = self._store.get_node(input.id)
        except KeyError:
            raise UseCaseError("no such node: %s" % input.id)

        children = self._store.children(node.id)
        structural = [c for c in children if c.type in _STRUCTURAL_TYPES]
        if structural:
            raise UseCaseError(
                "refusing to delete %s: %d structural child(ren) present - delete them first"
                % (node.id, len(structural))
            )

        step_ids = {c.id for c in children if c.type == "step"}
        if node.type == "step":
            step_ids.add(node.id)
        live = self._live_step(step_ids)
        if live is not None:
            raise UseCaseError(
                "refusing to delete %s: step %s is claimed by a live worker "
                "- stop the pool or sweep first" % (node.id, live)
            )

        if node.type == "item" and not input.force and self._worktree_dirty(node.id):
            raise UseCaseError(
                "refusing to delete %s: worktree has uncommitted changes "
                "- commit or discard, or use --force" % node.id
            )

        worktree_removed = False
        if node.type == "item":
            self._worktrees.remove(node.id)
            worktree_removed = True

        steps_removed = 0
        for c in children:
            if c.type == "step":
                self._store.delete(c.id)
                steps_removed += 1

        self._store.delete(node.id)
        return RemoveNodeResponse(
            id=node.id, steps_removed=steps_removed, worktree_removed=worktree_removed
        )
