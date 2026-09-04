import ast


def _dict_keys(node):
    out = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Dict):
            for key in child.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    out.add(key.value)
    return out


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


ON_THE_READ_SURFACE = ("Step", "Item", "PhaseRun", "Pass", "NodeView")


def json_surface(sources, cli_source=""):
    keys = set()
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in ON_THE_READ_SURFACE:
                continue
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "as_dict":
                    keys |= _dict_keys(child)
                    keys |= _subscript_keys(child)
    if cli_source:
        tree = ast.parse(cli_source)
        keys |= _subscript_keys(tree)
    return keys
