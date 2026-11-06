from lightcycle.domain.pool import stack_shape
from lightcycle.domain.runs import RunState

UNLAYERED = "unlayered"


def _prs_of_run(run):
    if not run.pr:
        return 0
    record = stack_shape.decode(getattr(run, "stack_seen", None))
    return len(record) if record else 1


def prs_of(runs):
    return sum(_prs_of_run(run) for run in runs)


def prs_merged_of(runs):
    return sum(_prs_of_run(run) for run in runs if run.state == RunState.MERGED)


def finding_layer(finding):
    return finding.get("layer")


def layer_rejections(findings):
    counts = {}
    layers = [finding_layer(f) for f in (findings or [])]
    for layer in dict.fromkeys(l for l in layers if l is not None):
        counts[str(layer)] = 1
    if not layers or any(l is None for l in layers):
        counts[UNLAYERED] = 1
    return counts


def findings_by_layer(findings):
    counts = {}
    for finding in findings or []:
        layer = finding_layer(finding)
        key = UNLAYERED if layer is None else str(layer)
        counts[key] = counts.get(key, 0) + 1
    return counts


def verdict_layers(findings):
    return sorted({finding_layer(f) for f in (findings or []) if finding_layer(f) is not None})
