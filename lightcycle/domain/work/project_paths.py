import os
import re


def is_under(path, root):
    path = os.path.normpath(path)
    root = os.path.normpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def translate(path, old_root, new_root):
    if not is_under(path, old_root):
        return path
    rel = os.path.relpath(os.path.normpath(path), os.path.normpath(old_root))
    return os.path.normpath(new_root) if rel == "." else os.path.join(os.path.normpath(new_root), rel)


def tilde_form(path, home):
    if not home or not is_under(path, home):
        return None
    rel = os.path.relpath(os.path.normpath(path), os.path.normpath(home))
    return "~" if rel == "." else "~/" + rel


def rewrite_value(value, old_root, new_root, home):
    old_abs = os.path.normpath(old_root)
    new_abs = os.path.normpath(new_root)
    old_tilde = tilde_form(old_abs, home)
    new_tilde = tilde_form(new_abs, home)
    forms = [old_abs] + ([old_tilde] if old_tilde else [])
    pattern = re.compile(
        "(?<![^\\s'\"=])(?:%s)(?=[/\\s'\"]|$)" % "|".join(re.escape(f) for f in forms)
    )

    def replace(match):
        if old_tilde and match.group(0) == old_tilde:
            return new_tilde or new_abs
        return new_abs

    result = pattern.sub(replace, value)
    return result if result != value else None
