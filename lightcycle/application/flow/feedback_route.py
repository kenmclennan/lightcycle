from lightcycle.domain.work.state import State


class FeedbackRoute:
    @staticmethod
    def watched_close(store, flow, step_id, outcome):
        node = store.get_node(step_id)
        if node.state == State.DONE:
            return None
        routes = flow.load_flow(flow.workflow_for(node)).step_def(node.stage).feedback_routes
        watched_outcome = routes.get(outcome)
        if watched_outcome is None:
            return None
        return (node.watched_step, watched_outcome)
