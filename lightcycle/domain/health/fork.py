from collections import namedtuple

Fork = namedtuple("Fork", "item phase steps")


def main_path_stages(graph):
    stages = set()
    if graph.entry:
        stages.add(graph.entry)
    for outs in graph.edges.values():
        stages.update(t for t in outs.values() if t)
    return stages


def forks(open_steps, main_stages_of_item):
    groups = {}
    for item, step_id, stage, phase in open_steps:
        main = main_stages_of_item(item)
        if not main or stage not in main:
            continue
        groups.setdefault((item, phase), []).append((step_id, stage))
    return [
        Fork(item, phase, tuple(steps))
        for (item, phase), steps in groups.items()
        if len(steps) >= 2
    ]
