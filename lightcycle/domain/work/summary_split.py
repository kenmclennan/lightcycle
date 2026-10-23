import re
from typing import Dict, List, Mapping, Optional, Tuple

SUMMARY_LABELS = ("Delivered", "Fixed", "Improved")

_BRACKET_AT_END = re.compile(r"\[([^\[\]]*)\][.;,\s]*$")


def _first_resolving_id(bullet, project_by_item_id):
    match = _BRACKET_AT_END.search(bullet)
    if match is None:
        return None
    for item_id in re.split(r"[,\s]+", match.group(1)):
        if item_id in project_by_item_id:
            return item_id
    return None


def _collapse(lines):
    out = []
    for line in lines:
        if line.strip() == "" and (not out or out[-1].strip() == ""):
            continue
        out.append(line)
    text = "\n".join(out).strip()
    return text or None


def split_summary(
    text: str, project_by_item_id: Mapping[str, Optional[str]]
) -> Tuple[Dict[Optional[str], Dict[str, List[str]]], Optional[str]]:
    sections: Dict[Optional[str], Dict[str, List[str]]] = {}
    kept: List[str] = []
    label_at: Dict[int, List[int]] = {}
    label_index = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in SUMMARY_LABELS:
            kept.append(line)
            label_index = len(kept) - 1
            label_at[label_index] = [0, 0, stripped]
            continue
        if label_index is not None and stripped.startswith("- "):
            item_id = _first_resolving_id(stripped, project_by_item_id)
            if item_id is not None:
                project = project_by_item_id[item_id]
                label = label_at[label_index][2]
                sections.setdefault(project, {}).setdefault(label, []).append(stripped)
                label_at[label_index][0] += 1
                continue
            label_at[label_index][1] += 1
        elif stripped:
            label_index = None
        kept.append(line)
    dropped = {i for i, (moved, left, _) in label_at.items() if moved and not left}
    remainder = [line for i, line in enumerate(kept) if i not in dropped]
    return sections, _collapse(remainder)
