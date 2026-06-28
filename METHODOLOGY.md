# the-grid methodology

the-grid is two things at once: an agent-pipeline **engine**, and a **methodology** for building
software with such a pipeline. This document is the methodology - the principles and the reasoning
behind `driver.md` (the playbook) and `CLAUDE.md` (the conventions). It is a living document: update
it as the method is discovered. The method is the product; the features only prove it.

## The core insight: human attention is the scarce resource

The scarce resource is human **attention** - and attention is fragile. It fragments under noise,
context-switching, and chaos; it cannot be parallelised or regenerated; and it is the only thing in
this system that carries _intent_. (It does not help that LLM generation outruns human review:
plausible, detailed output arrives faster than a human can falsify it, and plausibility is exactly
what defeats review under fatigue - so even reviewing can become noise that erodes focus.)

Attention should be spent where only a human can spend it - on **design, discovery, learning,
creativity, and validation**, the generative, high-judgment work. Everything else - the bookkeeping,
the polling, the chasing, the re-deriving, the wall-of-plausible-text reviews - is noise that _steals_
focus, and the abundant, parallel agents should absorb it.

So the method's goal is not merely "more throughput." It is to **strip away the noise and fragmentation
that scatter attention** and leave a calmer, more focused experience - so the human's attention lands,
undivided, on the work that is worth a human. Almost every principle below is an instance of that:
remove a source of friction, noise, or context-switching so focus can hold.

## What `tg` is - and isn't

`tg` is the **hub and the planning assistant**. It owns the **coordination**: capturing todos, the
workflow that turns a todo into a spec and carries it through build, and handing each artifact to the
right surface for review and pulling the feedback back. It does **not** own the **craft**: writing the
spec (delegated to the best spec-writer available - vanilla Claude or a skill, never an engine-imposed
format) or the review itself (which happens on the artifact's natural surface - GitHub comments, an
editor - not in a `tg`-rendered gate). `tg` is not a universal solver for agentic development; work
with a better natural home lives there, and `tg` links out and pulls the feedback back. It conducts;
the work happens in the right places. _This boundary is what keeps the engine light and agnostic: it
owns the moving-of-work, not the doing-of-work._

## Principles

### Encode decisions where they are enforced

A way-of-working decision is not real until it is written somewhere it is _enforced_ - otherwise it
rots in conversation, and you re-derive it, drift from it, or revert a working fix because nobody
recorded why it was there. Place each decision by **scope**: generic agent competence in the step
file; this project's conventions in its `CLAUDE.md`; cross-project style in the global config; the
driver's way-of-working in `driver.md`; the reasoning here. _Discovered the hard way: we kept making
decisions in chat and nearly acted on a model (epics) we had never written down._

### Keep the engine agnostic; conventions go to the project

The engine builds _any_ repo. So `tg` and `core` must hold only generic task/process primitives - no
hardcoded step names, required named artifacts, or per-workflow commands. The workflow is the user's,
and it lives in editable step markdown composed from primitives; a project's specifics live in that
project's `CLAUDE.md`, which the agnostic agents read. _Discovered via the `tg plan-add` trap: a
command that baked a `build` step and a required `spec` into the engine; reverted in favour of the
planner composing `tg file --blocked-by`._

### Substrate by hand; additive through the pipeline

The pipeline cannot build the loader it runs on. Anything that changes how the engine loads, spawns,
or composes itself is **substrate** - the driver builds it by hand. Everything additive (new commands,
new steps, features) goes through develop -> build like any work. _Discovered renaming `agents/` ->
`steps/`: a running pool kept executing the old code because you cannot safely rebuild the thing
currently running._

### State lives in the store, not in processes

Work is durable in the bead store, not in any worker or pool process. The pool is a stateless engine
that polls `bd ready` and runs whatever is ready; kill it, suspend the laptop, lose a worker - nothing
is lost, because the truth is in the store and `sweep` reconciles on restart. Two corollaries:
**gate held work with `--blocked-by`** (the store releases it automatically - never hand-track what
goes next), and **prefer pull (poll the store) over push** (more robust; push is only a latency
optimisation). _Discovered when an overnight suspend resumed cleanly, and when hand-tracking "held"
work turned out to be redundant with a dependency the store already enforced._

### The lifecycle: human at the edges, pool in the middle

Work flows: **capture -> refine -> develop -> review -> plan -> build -> ship.** The human (with the
driver) touches the human-facing stages - shaping ideas, deciding scope, gating specs and PRs - while
the pool runs the autonomous middle (build, review, open-pr, watch-pr). The human's scarce time is
spent at the _edges_ (define and gate), never the mechanical middle.

### Dependencies are story-level, not step-level

When one piece of work needs another, the dependency is between **stories**, and it clears when the
predecessor story **closes** - not when any step inside it finishes. A story is the unit of
completion; how it closes (built, reviewed, merged, abandoned) is opaque to the graph. This keeps the
planner workflow-agnostic - it wires story to story and never names build, review, or merge - and it
means "merge" is not a first-class event the system must define: merging is just one way a story
closes. _Discovered when the planner's first run blocked dependents on predecessor build tasks, which
close at build-done; a dependent would have started before the predecessor merged, building from a
main that did not yet contain its work._

### Epics are coherent outcomes; refinement consolidates

An **epic** is a coherent _outcome_, not a promoted todo and not a matter of size: some epics are one
big thing, some are several related small ones. Refinement is the deliberate act of shaping rough,
cheap, overlapping backlog captures into scoped epics, consolidating related items. The payoff is that
**active epics are the current focus areas** - the prioritisation signal a flat todo list cannot give.

### The self-improvement loop

The system improves itself: reflections, objective signals, and logs feed a retro that proposes
sharpenings of the steps and conventions; the human gates those changes. The recurring pattern is that
the human catches what the agent reviewer misses, and that catch becomes a sharpened, durable
convention - so feedback compounds into competence. _Discovered when off-pattern code merged, the
gap led to enriching `CLAUDE.md` and the reviewer, and the next builds came back clean - the system
correcting its own mistake through its own pipeline._

### Falsifiable specs; prime every review

A spec exists to be reviewed and built against, so it must be **falsifiable** - concrete enough that
a human can check it and an agent can verify the work, not a wall of plausible prose. _How_ a spec
achieves that (its shape, sections, whether it uses diagrams) is deliberately not fixed here: the
engine stays agnostic about spec form, and we lean on the best spec-writing tools rather than baking a
house format into the system. The goal is the property (falsifiable, reviewable), not a template.
_Discovered after merging a PR un-primed and having to dig for the issue by hand._

### Pace by the human

Co-design one decision at a time: propose, confirm, record. The human sets the session's objective and
its pace; the driver never races ahead or batch-decides. This is the scarce-resource principle applied
to the conversation itself.

## What is still being discovered

The method is not finished. The open frontiers, where the principles are still forming:

- **Engagement scheduler** - managing the human's attention and time across session modes (push a
  goal / refine / queue-and-leave / review) and an offline mode that fills their absence with bounded
  autonomous work, rate-limited to their review bandwidth.
- **Refinement tooling** - making "rough backlog -> scoped epics" a real, supported step, with a
  focus-area view and recorded lineage.
- **Measurement and the retro** - turning the lifecycle's own history into the signal that drives the
  self-improvement loop.
- **Productization** - the engine-vs-`$HOME` split that lets a user own and customise their workflow,
  specs, and data, durably backed up.
