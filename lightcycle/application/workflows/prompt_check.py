from pathlib import Path

from lightcycle.domain.contracts.cli_surface import cli_surface
from lightcycle.domain.contracts.json_surface import json_surface
from lightcycle.domain.contracts.prompt_commands import json_field_reads, lc_calls
from lightcycle.domain.work import all_states, missing_for_state

_PLACEHOLDER = "<"


def check_prompt_commands(step_texts, cli_source, domain_sources=()):
    surface = cli_surface(cli_source)
    emitted = json_surface(domain_sources, cli_source) if domain_sources else None
    problems = {}
    for name, text in sorted(step_texts.items()):
        messages = []
        for call in lc_calls(text):
            messages += _check_call(call, surface)
        if emitted is not None:
            for read in json_field_reads(text):
                if read["field"] not in emitted:
                    messages.append(
                        "line %d: the engine emits no `.%s` - a step reading it gets null"
                        % (read["line"], read["field"])
                    )
        if messages:
            problems[name] = messages
    return problems


def _check_call(call, surface):
    verb, flags = call["verb"], call["flags"]
    if verb not in surface:
        return [
            "line %d: `lc %s` is not a command: %s" % (call["line"], verb, call["text"])
        ]
    unknown = sorted(f for f in flags if f not in surface[verb])
    messages = [
        "line %d: `lc %s` does not accept --%s: %s"
        % (call["line"], verb, f, call["text"])
        for f in unknown
    ]
    state = call["state"]
    if state and not state.startswith(_PLACEHOLDER):
        if state not in all_states():
            messages.append(
                "line %d: --state %s is not a state: %s"
                % (call["line"], state, call["text"])
            )
        for need in missing_for_state(state, flags):
            messages.append(
                "line %d: --state %s requires --%s: %s"
                % (call["line"], state, need, call["text"])
            )
    return messages


def engine_sources():
    root = Path(__file__).resolve().parents[1]
    cli = (root.parent / "cli.py").read_text()
    domain = [p.read_text() for p in sorted((root.parent / "domain").rglob("*.py"))]
    return cli, domain


def prompt_drift_detail(drift):
    if not drift:
        return None
    lines = [
        "%d prompt problem(s) - a step following them gets an error or a null:"
        % sum(len(m) for m in drift.values())
    ]
    for step, messages in sorted(drift.items()):
        for message in messages:
            lines.append("  %s %s" % (step, message))
    lines.append(
        "fix the step prompts in the source and push, or pull a ref that targets this engine."
    )
    return "\n".join(lines)
