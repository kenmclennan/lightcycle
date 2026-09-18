import ast
import re
from dataclasses import dataclass

from textual.css.stylesheet import Stylesheet

_INTERP_MARKER = "\x00"
_UNRESOLVED = object()


@dataclass(frozen=True)
class WidgetIdentity:
    type_name: str
    widget_id: str | None = None

    def selector(self) -> str:
        return "#%s" % self.widget_id if self.widget_id else self.type_name


@dataclass(frozen=True)
class Violation:
    file: str
    cls: str
    identity: WidgetIdentity


@dataclass(frozen=True)
class UnresolvedSite:
    file: str
    cls: str
    line: int
    expression: str


def find_violations(sources):
    parsed = {file: ast.parse(source, filename=file) for file, source in sources.items()}
    declared_display = _pooled_css_declared_display(parsed.values())

    violations = []
    unresolved = []
    for file, tree in parsed.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            toggled, class_unresolved = _analyze_class(file, node)
            unresolved.extend(class_unresolved)
            for identity, safe in toggled.items():
                if not safe and not _css_safe(identity, declared_display):
                    violations.append(Violation(file, node.name, identity))
    return violations, unresolved


def _css_safe(identity, declared_display):
    if identity.widget_id and declared_display.get("#%s" % identity.widget_id) == "none":
        return True
    return declared_display.get(identity.type_name) == "none"


def _analyze_class(file, cls_node):
    methods = {
        n.name: n for n in cls_node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    compose_func = methods.get("compose")
    if compose_func is None:
        return {}, []

    compose_widgets = _analyze_compose(compose_func)
    closure = _closure_methods(methods)

    toggled = {}
    unresolved = []
    for name, func in methods.items():
        if name == "compose":
            continue
        for resolved, lineno, expression in _scan_toggle_sites(func):
            if resolved is _UNRESOLVED:
                unresolved.append(UnresolvedSite(file, cls_node.name, lineno, expression))
                continue
            identity, signal1 = _match_compose_widget(resolved, compose_widgets)
            signal2 = name in closure
            toggled[identity] = toggled.get(identity, False) or signal1 or signal2

    return toggled, unresolved


def _match_compose_widget(resolved, compose_widgets):
    for identity, safe in compose_widgets.items():
        if _identities_match(resolved, identity):
            return identity, safe
    return resolved, False


def _identities_match(a, b):
    if a.type_name != b.type_name:
        return False
    return a.widget_id == b.widget_id or a.widget_id is None or b.widget_id is None


def _analyze_compose(func):
    widgets = {}
    var_identity = {}
    var_safe = {}

    def register(identity):
        widgets.setdefault(identity, False)

    def register_yield(expr):
        if isinstance(expr, ast.Name) and expr.id in var_identity:
            identity = var_identity[expr.id]
            widgets[identity] = widgets.get(identity, False) or var_safe.get(expr.id, False)
        elif isinstance(expr, ast.Call):
            for nested in _iter_widget_calls(expr):
                nested_identity = _extract_identity(nested)
                if nested_identity is not None:
                    register(nested_identity)

    for stmt in _iter_statements(func.body):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            varname = stmt.targets[0].id
            value = stmt.value
            if isinstance(value, ast.Call):
                identity = _extract_identity(value)
                if identity is not None:
                    var_identity[varname] = identity
                    var_safe[varname] = False
                for nested in _iter_widget_calls(value):
                    nested_identity = _extract_identity(nested)
                    if nested_identity is not None:
                        register(nested_identity)
            continue
        target_value = _display_target_value(stmt)
        if target_value is not None:
            if isinstance(target_value, ast.Name) and target_value.id in var_identity:
                var_safe[target_value.id] = True
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Yield) and stmt.value.value is not None:
            register_yield(stmt.value.value)

    return widgets


def _scan_toggle_sites(func):
    var_identity = {}
    sites = []
    for stmt in _iter_statements(func.body):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            value = stmt.value
            if isinstance(value, ast.Call):
                resolved = _resolve_query_one(value)
                if resolved is not None:
                    var_identity[stmt.targets[0].id] = resolved
            continue
        target_value = _display_target_value(stmt)
        if target_value is None:
            continue
        if isinstance(target_value, ast.Call):
            resolved = _resolve_query_one(target_value)
            if resolved is None:
                resolved = _UNRESOLVED
        elif isinstance(target_value, ast.Name):
            resolved = var_identity.get(target_value.id, _UNRESOLVED)
        else:
            resolved = _UNRESOLVED
        sites.append((resolved, stmt.lineno, ast.unparse(target_value)))
    return sites


def _display_target_value(stmt):
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
        return None
    target = stmt.targets[0]
    if not (isinstance(target, ast.Attribute) and target.attr == "display"):
        return None
    return target.value


def _resolve_query_one(call):
    if not (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "query_one"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
    ):
        return None
    if not call.args:
        return _UNRESOLVED
    first = call.args[0]
    type_arg = call.args[1] if len(call.args) > 1 else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        selector = first.value
        widget_id = selector[1:] if selector.startswith("#") else None
        if type_arg is not None:
            type_name = _type_name_from_expr(type_arg)
        elif widget_id is None:
            type_name = selector
        else:
            type_name = None
        if type_name is None:
            return _UNRESOLVED
        return WidgetIdentity(type_name, widget_id)
    if type_arg is None:
        type_name = _type_name_from_expr(first)
        if type_name is not None:
            return WidgetIdentity(type_name, None)
    return _UNRESOLVED


def _type_name_from_expr(expr):
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _extract_identity(call):
    func = call.func
    if isinstance(func, ast.Name):
        type_name = func.id
    elif isinstance(func, ast.Attribute):
        type_name = func.attr
    else:
        return None
    widget_id = None
    for kw in call.keywords:
        if kw.arg == "id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            widget_id = kw.value.value
    return WidgetIdentity(type_name, widget_id)


def _iter_widget_calls(call):
    yield call
    for arg in call.args:
        if isinstance(arg, ast.Call):
            yield from _iter_widget_calls(arg)


def _iter_statements(stmts):
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from _iter_statements(stmt.body)
            yield from _iter_statements(stmt.orelse)
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            yield from _iter_statements(stmt.body)
            yield from _iter_statements(stmt.orelse)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from _iter_statements(stmt.body)
        elif isinstance(stmt, ast.Try):
            yield from _iter_statements(stmt.body)
            for handler in stmt.handlers:
                yield from _iter_statements(handler.body)
            yield from _iter_statements(stmt.orelse)
            yield from _iter_statements(stmt.finalbody)


def _self_calls_in_stmt(stmt):
    calls = []

    def walk(node):
        if isinstance(node, ast.Lambda):
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            calls.append(node)
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(stmt)
    return calls


def _closure_methods(methods):
    seed = [name for name in ("compose", "on_mount") if name in methods]
    closure = set(seed)
    queue = list(seed)
    while queue:
        name = queue.pop()
        for stmt in _iter_statements(methods[name].body):
            for call in _self_calls_in_stmt(stmt):
                called = call.func.attr
                if called in methods and called not in closure:
                    closure.add(called)
                    queue.append(called)
    return closure


def _pooled_css_declared_display(trees):
    texts = []
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "CSS" for t in stmt.targets)
                ):
                    continue
                text = _css_text(stmt.value)
                if text:
                    texts.append(text)

    declared = {}
    if not texts:
        return declared

    stylesheet = Stylesheet()
    stylesheet.add_source("\n".join(texts), read_from=("tui_display_guard", "tui_display_guard"))
    stylesheet.parse()
    for rule_set in stylesheet.rules:
        if not rule_set.styles.has_rule("display"):
            continue
        value = rule_set.styles.get_rule("display")
        for selector_set in rule_set.selector_set:
            declared[selector_set.css] = value
    return declared


def _css_text(value_node):
    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
        return value_node.value
    if isinstance(value_node, ast.JoinedStr):
        parts = []
        for value in value_node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append(_INTERP_MARKER)
        raw = re.sub(r"^\s*" + _INTERP_MARKER + r"\s*$", "", "".join(parts), flags=re.M)
        return re.sub(r"[A-Za-z-]+\s*:[^;{}]*" + _INTERP_MARKER + r"[^;{}]*;", "", raw)
    return None
