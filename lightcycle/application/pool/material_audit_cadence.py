from dataclasses import dataclass, field
from typing import List

from lightcycle.application.flow.engine_steps import MATERIAL_AUDIT_STEP, RETRO_ORIGIN_LABEL
from lightcycle.domain.work import State, parse_timestamp

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class MaterialAuditCadenceResponse:
    fired: List[str] = field(default_factory=list)


class MaterialAuditCadenceUseCase:

    def __init__(self, store, config):
        self._store = store
        self._config = config

    def execute(self, now: float) -> MaterialAuditCadenceResponse:
        prior = self._store.steps_at_step(MATERIAL_AUDIT_STEP)
        if any(s.state != State.DONE for s in prior):
            return MaterialAuditCadenceResponse()

        last = max(prior, key=lambda s: parse_timestamp(s.created_at), default=None)
        window = self._config.material_audit_days() * _SECONDS_PER_DAY
        if last is not None and now - parse_timestamp(last.created_at).timestamp() < window:
            return MaterialAuditCadenceResponse()

        since = parse_timestamp(last.created_at).date().isoformat() if last else "none"
        description = "materials: guidance\nsince: %s\nprevious: %s" % (
            since, last.id if last else "none")
        with self._store.transaction():
            item_id = self._store.create_item(
                "Audit of guidance entries", description,
                shortcode=self._config.audit_shortcode())
            self._store.label_add(item_id, RETRO_ORIGIN_LABEL)
            tid = self._store.create_step(
                step=MATERIAL_AUDIT_STEP, role="agent", parent=item_id)
        return MaterialAuditCadenceResponse(fired=[tid])
