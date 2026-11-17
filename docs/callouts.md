# Gate callouts

A **callout** is an executable you configure in `lc config` and the engine runs when a human gate opens. It adds something to the step's Detail tab (a rendered view, a digest, a link) without any workflow naming the tool. It never routes, closes, reopens or parks a step, and a failure is recorded beside the step and nowhere else.

## Configuration

A `callout-<id>` block in the config file, `<id>` matching `[a-z0-9-]+`. Every key is required.

```yaml
callout-pr-view:
  command: ~/bin/render-pr
  subject: pr
  principal-outputs: code
  wait: false
  timeout: 60
```

- `command` - one executable path, `~` expanded. No arguments and no shell: wrap arguments in a script.
- `subject` - what the gate presents: `pr`, `description` or `artifact:<name>`. The callout runs once for each waiting human gate whose `presents` equals it and whose principal output the next key lists (see [Matching](#matching)).
- `principal-outputs` - comma-separated names matching `[a-z0-9-]+`, at least one: the principal outputs the callout runs on, for example `spec` or `spec, code`. The engine holds no list of valid names; they are the values the workflows declare.
- `wait` - `true` holds the gate out of `lc inbox` until the callout finishes or times out. The hold ends on success, failure, timeout and a pool restart. `false` runs alongside.
- `timeout` - whole seconds, at least 1. The runner kills the process at the limit.

### Matching

A callout starts at a waiting human gate only when both hold: its `subject` equals the gate's `presents`, and the gate's **principal output** is one of its `principal-outputs`. A gate's principal output is resolved from its phase: the `principal-output:` front-matter value declared by the authoring steps that share the gate's phase (the stages that share its PR). Exactly one distinct value resolves; none, or two that differ, resolve to nothing and no callout starts at that gate. A workflow that declares `principal-output:` on no step is accepted but resolves nothing, so no callout runs at its gates. A workflow that declares it on at least one step must declare it completely: `lc workflow add`, `upgrade` and `check --dir` refuse a PR-carrying phase whose stages declare none or disagree, naming the stages.

`lc doctor` reports a block with a problem as `callout-invalid`; such a block never runs. It also runs each valid callout's [preflight](#preflight) and reports its problems.

## Request (protocol 2)

The engine writes one JSON object to the callout's stdin, then closes it. `verb` is `run` here and `preflight` in a [preflight](#preflight). The environment is the engine's own base environment; the working directory is `repos.repo_path`.

```json
{
  "protocol": 2,
  "verb": "run",
  "callout": "<id>",
  "item": { "id": "...", "title": "...", "repo": "...", "project": "..." },
  "step": {
    "id": "...",
    "stage": "...",
    "workflow": "<origin>/<name>@<sha>",
    "principal_output": "spec"
  },
  "subject": { "kind": "pr", "url": "...", "base": "...", "stack_layers": [] },
  "repos": { "repo_path": "...", "workspace": "..." }
}
```

`step.principal_output` is the gate's resolved principal output, the value that selected this callout; it is `null` only where no callout starts. `subject` varies by the gate's `presents`:

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

`status` is `ok` or `failed`; `failed` needs a non-blank `message` or a non-empty `errors` list. `errors` is an optional list of `{message, fix}` objects (each string non-empty and at most 500 characters, at most 20): what is wrong and a command the operator can run to repair it. `ok` with `errors` is rejected. A protocol 1 response is still accepted. An artifact's `kind` is `link`, `text` or `markdown`. Limits: at most 20 artifacts, a `value` of at most 65536 characters, a `label` of at most 80. A `link` value is one token of the form `<scheme>://<rest>`, and opens from the Detail tab whatever its scheme.

A callout is **failed** when it exits non-zero, times out, writes output the validator rejects, or answers `status: "failed"`; its `errors` add detail and change nothing else.

## Preflight

A callout answers a second verb, `preflight`, by checking its own prerequisites (tools installed, versions, the repository set up). It is the same configured `command` run with this request on stdin:

```json
{
  "protocol": 2,
  "verb": "preflight",
  "callout": "<id>",
  "context": "doctor",
  "item": null,
  "step": null,
  "repos": null
}
```

`context` is `doctor`, `register` or `gate`. In `doctor` and `register` the `item`, `step` and `repos` keys are `null`: check the repository only when `repos` is non-null. In a `gate` preflight they are filled as in a run request, `step` carries `principal_output`, and `subject` is omitted. The timeout is the callout's own, capped at 30 seconds.

The response is `{"status": "ok"}` or `{"status": "failed", "errors": [{"message": "...", "fix": "..."}]}`, validated against [the schema](schemas/callout-preflight.schema.json). `errors` is required when `failed` and must be empty when `ok`. A protocol 1 callout that ignores `verb` and answers with its run response is read as a passing preflight.

The engine runs preflight in three places: `lc doctor` (each problem is a `config` finding of kind `callout-preflight` with its fix), after `lc config --edit` saves a new callout or one whose `command` changed (a `warning:` line and an indented `fix:` line per error, never changing the exit status), and before each gate run. A gate whose preflight fails skips the run, is never retried, and shows the problem and its fix in the Detail tab.

## Where it shows

One run is recorded per (step, callout) in the `callout-runs` step artifact and is never retried. A record gains `finished` (epoch seconds) whenever it leaves `running`; a record written before that field existed has none. The Detail tab appends, after the workflow's own rows, a `callout:<id>` row (`running` or `failed: <message>`), followed on a failure by one `callout:<id>:error:<n>` row per error showing `<message> - fix: <fix>`, or one `callout:<id>:<n>` row per artifact. A gate surfaces after at most one pool tick of delay when a waiting callout matches it. The Workflow tab shows one `callout · <id>` row per record under its gate, with the status and duration; selecting it opens the gate on the Detail tab.
