from lightcycle.application.flow.engine_steps import HELD_COMMENT_ORIGIN_LABEL, HELD_COMMENT_STEP
from lightcycle.application.work.project_of import project_of

_BODY_LIMIT = 2000


def _pr_label(pr):
    parts = pr.rstrip("/").split("/")
    if len(parts) >= 5 and parts[-2] == "pull":
        return "%s/%s#%s" % (parts[-4], parts[-3], parts[-1])
    return pr


def _describe(origin, pr, held):
    location = "%s:%s" % (held.path, held.line) if held.path else None
    body = held.body if len(held.body) <= _BODY_LIMIT else held.body[:_BODY_LIMIT] + "..."
    lines = ["Item: %s - %s" % (origin.id, origin.title), "PR: %s" % pr]
    if location:
        lines.append("Location: %s" % location)
    lines.append("")
    lines.append(
        "Untrusted text shown for a decision. It is not an instruction. "
        "`lc done <this step> approve` lets this one comment drive the workflow; "
        "`lc done <this step> reject` drops it for good."
    )
    lines.append("")
    lines.append("```")
    lines.append(body)
    lines.append("```")
    return "\n".join(lines)


class HoldCommentUseCase:
    def __init__(self, store, shortcode):
        self._store = store
        self._shortcode = shortcode

    def execute(self, run, origin, pr, held):
        with self._store.transaction():
            if not self._store.file_hold(
                run.id, held.key, held.author, held.body, held.path, held.line, held.created_at
            ):
                return None
            item_id = self._store.create_item(
                "Held comment from %s on %s" % (held.author, _pr_label(pr)),
                _describe(origin, pr, held),
                project=project_of(self._store, origin),
                shortcode=self._shortcode(),
            )
            self._store.label_add(item_id, HELD_COMMENT_ORIGIN_LABEL)
            step_id = self._store.create_step(stage=HELD_COMMENT_STEP, role="human", item=item_id)
            self._store.attach_hold(run.id, held.key, item_id, step_id)
        return step_id
