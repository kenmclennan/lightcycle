import ast


def _flag_names(call):
    out = set()
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if arg.value.startswith("--"):
                out.add(arg.value[2:])
    return out


def _loop_flags(node):
    out = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.For):
            continue
        names = {
            elt.value for elt in ast.walk(child.iter)
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }
        for inner in ast.walk(child):
            if _is_add_argument(inner) and any(
                isinstance(a, ast.BinOp) or isinstance(a, ast.JoinedStr) for a in inner.args
            ):
                out |= names
    return out


def _is_add_argument(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
    )


def cli_surface(source):
    tree = ast.parse(source)
    surface = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("cmd_"):
            continue
        verb = node.name[len("cmd_"):].replace("_", "-")
        flags = set()
        for child in ast.walk(node):
            if _is_add_argument(child):
                flags |= _flag_names(child)
        flags |= _loop_flags(node)
        surface[verb] = flags
    return surface
