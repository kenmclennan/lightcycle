import ast
from pathlib import Path

from lightcycle.application.workflows.prompt_commands import json_field_reads, lc_calls
from lightcycle.cli_commands import flags_by_verb
from lightcycle.domain.contracts.json_surface import json_surface
from lightcycle.domain.work import all_states, missing_for_state

_PLACEHOLDER = "<"


def check_prompt_commands(step_texts, cli_surface, json_keys):
    problems = {}
    for name, text in sorted(step_texts.items()):
        messages = []
        for call in lc_calls(text):
            messages += _check_call(call, cli_surface)
        for read in json_field_reads(text):
            if read["field"] not in json_keys:
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


def _subscript_keys(tree):
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                out.add(target.slice.value)
    return out


READ_SURFACE_MODULES = (
    "application/flow/claim_step.py",
    "application/work/node_read_surface.py",
)


class PromptSurfaceUnavailable(Exception):
    pass


def extra_json_keys(fs):
    root = Path(__file__).resolve().parents[1]
    keys = set()
    for rel in READ_SURFACE_MODULES:
        data = fs.read_bytes(str(root.parent / rel))
        if data is None:
            raise PromptSurfaceUnavailable("could not read %s to determine the JSON surface" % rel)
        keys |= _subscript_keys(ast.parse(data.decode("utf-8")))
    return keys


def engine_sources(fs):
    return flags_by_verb(), json_surface() | extra_json_keys(fs)


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
