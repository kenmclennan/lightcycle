"""The pool subdomain: which workers to run this tick.

Provisional: these are the flow.py pool functions relocated verbatim. They become
the PoolPlan + Worker objects (and shed the bead wire-format) in the pool batch.
"""
from the_grid.domain.pool.plan import pool_plan, ready_roles_from_beads, ready_task_roles

__all__ = ["pool_plan", "ready_roles_from_beads", "ready_task_roles"]
