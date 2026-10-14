from lightcycle.domain.work.audit_criteria import material_criteria

_PROMPT = "steps/material-audit.md"


class ShowAuditCriteriaUseCase:

    def __init__(self, fs, config):
        self._fs = fs
        self._config = config

    def execute(self, material):
        path = "%s/%s" % (self._config.prompts_root(), _PROMPT)
        raw = self._fs.read_bytes(path)
        if raw is None:
            raise FileNotFoundError(path)
        return material_criteria(raw.decode("utf-8"), material)
