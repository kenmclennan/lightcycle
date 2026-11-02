from lightcycle.domain.work.state import State


def open_successors(step_id, siblings):
    return [
        s.id for s in siblings
        if getattr(s, "previous_step", None) == step_id and s.state != State.DONE
    ]
