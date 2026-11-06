import json
from dataclasses import dataclass
from typing import List, Optional

SHAPE_PREFIX = "stack shape changed: "


def encode(record) -> str:
    return json.dumps(record, sort_keys=True)


def decode(text) -> Optional[list]:
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list):
        return None
    if not all(isinstance(e, dict) and "number" in e and "state" in e for e in value):
        return None
    return value


def label(position, total, url) -> str:
    return "layer %d of %d (%s)" % (position, total, url)


def record_of(layers, observed_bases, previous) -> list:
    carried = {e["number"]: e.get("base") for e in (previous or [])}
    record = []
    for layer in layers:
        base = None
        if layer.state == "open":
            base = observed_bases.get(layer.url) or carried.get(layer.number)
        record.append({
            "number": layer.number, "state": layer.state, "head_ref": layer.head_ref,
            "base": base,
        })
    return record


@dataclass(frozen=True)
class ShapeDiff:
    differences: List[str]
    newly_merged: List[str]


def _numbers(record):
    return [e["number"] for e in record]


def compare(previous, layers, current, dissolved) -> ShapeDiff:
    if dissolved:
        if previous:
            return ShapeDiff(["the stack was dissolved"], [])
        return ShapeDiff([], [])
    total = len(layers)
    previous = previous or []
    prior = {e["number"]: e for e in previous}
    by_number = {l.number: (i + 1, l) for i, l in enumerate(layers)}
    differences = []
    newly_merged = []
    for position, entry in enumerate(previous, start=1):
        if entry["number"] not in by_number:
            differences.append(
                "layer %d of %d (#%s) was removed" % (position, len(previous), entry["number"])
            )
    for number, (position, layer) in by_number.items():
        if number not in prior:
            differences.append("%s was added" % label(position, total, layer.url))
    kept_before = [n for n in _numbers(previous) if n in by_number]
    kept_now = [n for n in (l.number for l in layers) if n in prior]
    if kept_before != kept_now:
        differences.append("the layers were reordered")
    merged_heads = {}
    open_below = False
    for position, layer in enumerate(layers, start=1):
        name = label(position, total, layer.url)
        was = prior.get(layer.number)
        if was is not None and was["state"] != layer.state:
            if was["state"] == "open" and layer.state == "closed":
                differences.append("%s closed without merging" % name)
            elif was["state"] == "open" and layer.state == "merged":
                if open_below:
                    differences.append("%s merged while a layer below it is still open" % name)
                else:
                    newly_merged.append(name)
            else:
                differences.append(
                    "%s changed state from %s to %s" % (name, was["state"], layer.state)
                )
        if layer.state == "open" and was is not None:
            observed = current[position - 1].get("base")
            if (observed is not None and observed != layer.base_ref
                    and observed != was.get("base") and observed not in merged_heads):
                differences.append(
                    "%s was retargeted onto %s, which is neither its lower layer nor the trunk"
                    % (name, observed)
                )
        if layer.state == "merged":
            merged_heads[layer.head_ref] = True
        elif layer.state == "open":
            open_below = True
    return ShapeDiff(differences, newly_merged)


def describe(differences) -> str:
    return SHAPE_PREFIX + "; ".join(differences)
