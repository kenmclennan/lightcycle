import json

from lightcycle.domain.work import callout_log_label
from lightcycle.domain.work.callout_preflight import (
    engine_errors,
    preflight_errors,
    preflight_timeout,
)
from lightcycle.domain.work.callout_response import PROTOCOL

_RUN_ERRORS = (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError)


class CalloutPreflightUseCase:
    def __init__(self, config, runner):
        self._config = config
        self._runner = runner

    def check(self, callout, context):
        limit = preflight_timeout(callout.timeout)
        request = {
            "protocol": PROTOCOL, "verb": "preflight", "callout": callout.id,
            "context": context, "item": None, "step": None, "repos": None,
        }
        try:
            result = self._runner.run(
                callout.command, self._config.expand_path("~"), self._config.base_env(),
                json.dumps(request), limit,
                callout_log_label("preflight-%s" % context, callout.id))
            return list(preflight_errors(result, limit))
        except _RUN_ERRORS as e:
            return list(engine_errors("could not run the command: %s" % e))
