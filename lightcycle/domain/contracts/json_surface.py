from lightcycle.domain.runs.pass_record import Pass
from lightcycle.domain.runs.phase_run import PhaseRun
from lightcycle.domain.work.item import Item
from lightcycle.domain.work.node_view import NodeView
from lightcycle.domain.work.step import Step


def json_surface():
    keys = set()
    keys |= Item(id="x").as_dict().keys()
    step = Step(id="x", item="y")
    keys |= step.as_dict().keys()
    keys |= NodeView(step=step, item_artifacts=[]).as_dict().keys()
    keys |= PhaseRun(id="x", item="y", pass_id="z").as_dict().keys()
    keys |= Pass(id="x", item="y", n=1).as_dict().keys()
    return keys
