# Gate callouts

A **callout** is an executable you configure in `lc config` and the engine runs when a human gate opens. It adds something to the step's Detail tab (a rendered view, a digest, a link) without any workflow naming the tool. It never routes, closes, reopens or parks a step, and a failure is recorded beside the step and nowhere else.

## Configuration

A `callout-<id>` block in the config file, `<id>` matching `[a-z0-9-]+`. Every key is required.

```yaml
callout-pr-view:
  command: ~/bin/render-pr
  subject: pr
  wait: false
  timeout: 60
```

- `command` - one executable path, `~` expanded. No arguments and no shell: wrap arguments in a script.
- `subject` - what the gate presents: `pr`, `description` or `artifact:<name>`. The callout runs once for each waiting human gate whose `presents` equals it.
- `wait` - `true` holds the gate out of `lc inbox` until the callout finishes or times out. The hold ends on success, failure, timeout and a pool restart. `false` runs alongside.
- `timeout` - whole seconds, at least 1. The runner kills the process at the limit.

`lc doctor` reports a block with a problem as `callout-invalid`; such a block never runs.

## Request (protocol 1)

The engine writes one JSON object to the callout's stdin, then closes it. The environment is the engine's own base environment; the working directory is `repos.repo_path`.

```json
{
  "protocol": 1,
  "callout": "<id>",
  "item": { "id": "...", "title": "...", "repo": "...", "project": "..." },
  "step": { "id": "...", "stage": "...", "workflow": "<origin>/<name>@<sha>" },
  "subject": { "kind": "pr", "url": "...", "base": "...", "stack_layers": [] },
  "repos": { "repo_path": "...", "workspace": "..." }
}
```

`subject` varies by the gate's `presents`:

- `pr`: `kind`, `url`, `base` and `stack_layers` (each layer has `number`, `url`, `head_ref`, `base_ref`, `head_sha`, `state`). When the stack read fails the key is `stack_error` instead.
- `description`: `{"kind": "description", "value": "..."}`.
- `artifact:<name>`: `{"kind": "artifact", "name": "...", "value": "..."}`; for a spec gate `name` is `spec` and `value` is the spec path.

## Response

One JSON object on stdout, validated against [the schema](schemas/callout-response.schema.json):

```json
{
  "status": "ok",
  "message": "",
  "artifacts": [{ "label": "...", "kind": "link", "value": "..." }]
}
```

`status` is `ok` or `failed`; `message` is required when `failed`. An artifact's `kind` is `link`, `text` or `markdown`. Limits: at most 20 artifacts, a `value` of at most 65536 characters, a `label` of at most 80. A `link` value is one token of the form `<scheme>://<rest>`, and opens from the Detail tab whatever its scheme.

A callout is **failed** when it exits non-zero, times out, writes output the validator rejects, or answers `status: "failed"`.

## Where it shows

One run is recorded per (step, callout) in the `callout-runs` step artifact and is never retried. The Detail tab appends, after the workflow's own rows, a `callout:<id>` row (`running` or `failed: <message>`) or one `callout:<id>:<n>` row per artifact. A gate surfaces after at most one pool tick of delay when a waiting callout matches it.
