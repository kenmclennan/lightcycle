import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from pytest_bdd import parsers

STEP_TYPES = ("given", "when", "then")
PARSER_KINDS = ("parse", "re", "cfparse")


@dataclass(frozen=True)
class Step:
    module: str
    line: int
    func: str
    type: str
    kind: str
    pattern: str


@dataclass(frozen=True)
class Collision:
    generic: Step
    literal: Step


def _string_value(node) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _step_from_decorator(module: str, func_name: str, decorator) -> Optional[Step]:
    if not isinstance(decorator, ast.Call):
        return None
    if not isinstance(decorator.func, ast.Name) or decorator.func.id not in STEP_TYPES:
        return None
    if not decorator.args:
        return None
    pattern_arg = decorator.args[0]

    literal = _string_value(pattern_arg)
    if literal is not None:
        return Step(
            module=module,
            line=decorator.lineno,
            func=func_name,
            type=decorator.func.id,
            kind="literal",
            pattern=literal,
        )

    if (
        isinstance(pattern_arg, ast.Call)
        and isinstance(pattern_arg.func, ast.Attribute)
        and isinstance(pattern_arg.func.value, ast.Name)
        and pattern_arg.func.value.id == "parsers"
        and pattern_arg.func.attr in PARSER_KINDS
        and pattern_arg.args
    ):
        generic_pattern = _string_value(pattern_arg.args[0])
        if generic_pattern is not None:
            return Step(
                module=module,
                line=decorator.lineno,
                func=func_name,
                type=decorator.func.id,
                kind=pattern_arg.func.attr,
                pattern=generic_pattern,
            )

    return None


def extract_steps(source: str, label: str) -> List[Step]:
    tree = ast.parse(source)
    steps = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            step = _step_from_decorator(label, node.name, decorator)
            if step is not None:
                steps.append(step)
    return steps


def _parser_for(step: Step):
    return getattr(parsers, step.kind)(step.pattern)


def find_collisions(steps: List[Step]) -> List[Collision]:
    collisions = []
    for step_type in STEP_TYPES:
        group = [s for s in steps if s.type == step_type]
        generics = [s for s in group if s.kind != "literal"]
        literals = [s for s in group if s.kind == "literal"]
        for generic in generics:
            for literal in literals:
                if _parser_for(generic).is_matching(literal.pattern):
                    collisions.append(Collision(generic=generic, literal=literal))
    return collisions


def check_file(path: Path) -> List[Collision]:
    return find_collisions(extract_steps(path.read_text(), label=str(path)))


def check_files(paths: Iterable[Path]) -> List[Collision]:
    collisions = []
    for path in paths:
        collisions.extend(check_file(path))
    return collisions


def format_collisions(collisions: List[Collision]) -> str:
    lines = []
    for c in collisions:
        lines.append(
            "%s: %s collision - generic %s (line %d, pattern %r) matches literal %s (line %d, pattern %r)"
            % (
                c.generic.module,
                c.generic.type,
                c.generic.func,
                c.generic.line,
                c.generic.pattern,
                c.literal.func,
                c.literal.line,
                c.literal.pattern,
            )
        )
    return "\n".join(lines)
