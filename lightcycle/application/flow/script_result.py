from lightcycle.application.flow.complete_step import CompleteInput


def apply_stage_result(store, complete, step_id, output):
    for atype, value in output.artifacts.items():
        store.add_artifact(step_id, atype, value)
    return complete.execute(
        CompleteInput(step=step_id, outcome=output.outcome, note=output.note))
