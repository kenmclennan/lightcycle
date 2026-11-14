from lightcycle.domain.work.callout_response import (
    CalloutError,
    PreflightResponse,
    validate_preflight_response,
)

PREFLIGHT_TIMEOUT = 30
VERB_FIX = 'make the callout answer verb "preflight" - see docs/callouts.md'


def preflight_timeout(callout_timeout):
    return min(callout_timeout, PREFLIGHT_TIMEOUT)


def engine_errors(text):
    return (CalloutError("preflight: %s" % text, VERB_FIX),)


def preflight_errors(result, timeout):
    if result.timed_out:
        return engine_errors("timed out after %ss" % timeout)
    if result.exit_code is None:
        return engine_errors("could not run the command: %s" % (result.stderr_tail or "no exit status"))
    if result.exit_code != 0:
        return engine_errors("exited with code %s" % result.exit_code)
    parsed = validate_preflight_response(result.stdout)
    if not isinstance(parsed, PreflightResponse):
        return engine_errors("invalid response: %s" % parsed)
    return parsed.errors


def failure_message(message, errors):
    if message and message.strip():
        return message
    if not errors:
        return message
    first = errors[0].message
    if len(errors) > 1:
        return "%s (and %d more)" % (first, len(errors) - 1)
    return first
