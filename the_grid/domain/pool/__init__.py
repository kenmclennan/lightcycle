"""The pool subdomain: which workers to run this tick.

Provisional: still function-form. These become the PoolPlan + Worker objects in the
pool batch; they already read typed Tasks (no bead wire-format).
"""
from the_grid.domain.pool.plan import pool_plan, ready_roles, ready_task_roles

__all__ = ["pool_plan", "ready_roles", "ready_task_roles"]
