from lightcycle.application.feedback.hold_comment import describe_gate
from lightcycle.application.flow.complete_step import CompleteInput
from lightcycle.application.pool.stack_reads import read_stack
from lightcycle.config import ConfigError
from lightcycle.domain.feedback import (
    KIND_INLINE,
    HeldComment,
    roles_of,
    thread_answered_by_operator,
)
from lightcycle.ports.github import NotYetRead, ReadFailure

GATE_NOTE_PREFIX = "review-gates:"


def _kind_of(key):
    return key.partition(":")[0]


class ReviewGateRefreshUseCase:
    def __init__(self, store, github, complete, *, trusted_authors, review_bots):
        self._store = store
        self._github = github
        self._complete = complete
        self._trusted_authors = trusted_authors
        self._review_bots = review_bots

    def _urls(self, run, pr):
        if not run.stack:
            return [pr], None
        read = read_stack(self._github, run.stack)
        if not read.layers:
            return None, "the stack could not be read"
        return [layer.url for layer in read.layers], None

    def _full_read(self, urls):
        top_level, inline, reviews = [], [], []
        for url in urls:
            for name, sink in (
                ("comments_since", top_level), ("pull_comments", inline), ("reviews", reviews),
            ):
                value = getattr(self._github, name)(url, 0.0)
                if isinstance(value, ReadFailure):
                    return None, value
                sink.extend(value)
        return (top_level, inline, reviews), None

    def _note_unread(self, step, failure):
        if isinstance(failure, NotYetRead):
            detail = "the poll has not read the PR's comments yet"
        else:
            detail = "gh read failed (exit %d): %s" % (failure.returncode, failure.stderr)
        self._store.note_condition(
            step.id, "%s open review gates not refreshed - %s" % (GATE_NOTE_PREFIX, detail))

    def execute(self, step, pr, run):
        holds = self._store.open_holds(run.id)
        if not holds:
            return
        urls, reason = self._urls(run, pr)
        if urls is None:
            self._store.note_condition(
                step.id, "%s open review gates not refreshed - %s" % (GATE_NOTE_PREFIX, reason))
            return
        read, failure = self._full_read(urls)
        if failure is not None:
            self._note_unread(step, failure)
            return
        try:
            roles = roles_of(self._trusted_authors(), self._review_bots())
        except ConfigError:
            return
        top_level, inline, reviews = read
        self._store.clear_condition(step.id, GATE_NOTE_PREFIX)
        live = {}
        for kind, items in (("inline", inline), ("mention", top_level), ("review", reviews)):
            for obj in items:
                if obj.id is not None:
                    live["%s:%s" % (kind, obj.id)] = obj
        origin = self._store.get_item(step.item)
        for held in holds:
            self._refresh_one(step, pr, origin, held, live, inline, roles)

    def _close(self, held, outcome, note):
        if held.step_id is None:
            return
        self._complete.execute(
            CompleteInput(step=held.step_id, outcome=outcome, note=note, by_engine=True))

    def _refresh_one(self, step, pr, origin, held, live, inline, roles):
        obj = live.get(held.key)
        if obj is None:
            self._close(held, "withdrawn", "the reviewer deleted the comment")
            return
        if _kind_of(held.key) == KIND_INLINE and thread_answered_by_operator(obj, inline, roles):
            self._close(held, "superseded", "an operator answered in the thread")
            return
        if obj.body != held.body:
            self._store.update_hold_body(held.run_id, held.key, obj.body)
            refreshed = HeldComment(
                run_id=held.run_id, key=held.key, author=held.author, body=obj.body,
                created_at=held.created_at, path=held.path, line=held.line,
            )
            if held.item_id:
                self._store.edit_node(
                    held.item_id, description=describe_gate(origin, pr, refreshed, edited=True))
