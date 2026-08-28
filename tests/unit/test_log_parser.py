import unittest
from datetime import datetime

from lightcycle.adapters.log_parser import LogLineParser
from lightcycle.domain.work import LogKind

HOOK_STARTED = b'{"type":"system","subtype":"hook_started","hook_id":"12bf4ec6-d046-45ba-b784-638a124d5a90","hook_name":"SessionStart:startup","hook_event":"SessionStart","uuid":"f641bc47-9f32-4e14-b3b6-fbe735cfdb6b","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
HOOK_RESPONSE = b'{"type":"system","subtype":"hook_response","hook_id":"12bf4ec6-d046-45ba-b784-638a124d5a90","hook_name":"SessionStart:startup","hook_event":"SessionStart","output":"OK\\n","stdout":"OK\\n","stderr":"","exit_code":0,"outcome":"success","uuid":"d8e0c6f6-51fa-44ba-92c2-72b71583f20e","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
SYSTEM_INIT = b'{"type":"system","subtype":"init","cwd":"/Users/kenmclennan/workspace/projects/the-grid","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","tools":["Task","Bash","CronCreate","CronDelete","CronList","DesignSync","Edit","EnterWorktree","ExitWorktree","Monitor","NotebookEdit","PushNotification","Read","RemoteTrigger","ScheduleWakeup","SendMessage","Skill","TaskCreate","TaskGet","TaskList","TaskOutput","TaskStop","TaskUpdate","ToolSearch","WebFetch","WebSearch","Workflow","Write"],"mcp_servers":[{"name":"saga","status":"needs-auth"},{"name":"figma","status":"needs-auth"},{"name":"horde","status":"failed"}],"model":"claude-sonnet-4-6","permissionMode":"bypassPermissions","slash_commands":["backend-architecture-review","komment-killer","deep-research","code-review:code-review","frontend-design:frontend-design","superpowers:brainstorming","superpowers:dispatching-parallel-agents","superpowers:executing-plans","superpowers:finishing-a-development-branch","superpowers:receiving-code-review","superpowers:requesting-code-review","superpowers:subagent-driven-development","superpowers:systematic-debugging","superpowers:test-driven-development","superpowers:using-git-worktrees","superpowers:using-superpowers","superpowers:verification-before-completion","superpowers:writing-plans","superpowers:writing-skills","skill-creator:skill-creator","design-sync","update-config","verify","debug","code-review","simplify","batch","fewer-permission-prompts","loop","schedule","claude-api","run","run-skill-generator","clear","compact","config","context","heapdump","init","reload-skills","review","security-review","usage-credits","extra-usage","usage","insights","goal","team-onboarding"],"apiKeySource":"none","claude_code_version":"2.1.195","output_style":"default","agents":["claude","Explore","general-purpose","Plan","statusline-setup"],"skills":["backend-architecture-review","komment-killer","deep-research","frontend-design:frontend-design","superpowers:brainstorming","superpowers:dispatching-parallel-agents","superpowers:executing-plans","superpowers:finishing-a-development-branch","superpowers:receiving-code-review","superpowers:requesting-code-review","superpowers:subagent-driven-development","superpowers:systematic-debugging","superpowers:test-driven-development","superpowers:using-git-worktrees","superpowers:using-superpowers","superpowers:verification-before-completion","superpowers:writing-plans","superpowers:writing-skills","skill-creator:skill-creator","design-sync","update-config","verify","debug","code-review","simplify","batch","fewer-permission-prompts","loop","schedule","claude-api","run","run-skill-generator"],"plugins":[{"name":"frontend-design","path":"/Users/kenmclennan/.claude/plugins/cache/claude-plugins-official/frontend-design/unknown","source":"frontend-design@claude-plugins-official"},{"name":"superpowers","path":"/Users/kenmclennan/.claude/plugins/cache/claude-plugins-official/superpowers/6.1.1","source":"superpowers@claude-plugins-official"},{"name":"code-review","path":"/Users/kenmclennan/.claude/plugins/cache/claude-plugins-official/code-review/unknown","source":"code-review@claude-plugins-official"},{"name":"skill-creator","path":"/Users/kenmclennan/.claude/plugins/cache/claude-plugins-official/skill-creator/unknown","source":"skill-creator@claude-plugins-official"}],"analytics_disabled":false,"product_feedback_disabled":false,"uuid":"db74eae4-41d1-45c7-8f18-f8a415384411","memory_paths":{"auto":"/Users/kenmclennan/.claude/projects/-Users-kenmclennan-workspace-projects-the-grid/memory/"},"fast_mode_state":"off"}\n'
THINKING_TOKENS = b'{"type":"system","subtype":"thinking_tokens","estimated_tokens":13,"estimated_tokens_delta":13,"uuid":"906b8363-e1e4-4730-b898-331965536757","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
THINKING_BLOCK = b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01QotPaa8Cum5JvUGQio2xGS","type":"message","role":"assistant","content":[{"type":"thinking","thinking":"Let me start by claiming a task using `tg claim coder`.","signature":"Ev8BCmUIDxgCKkAALU6yg0ceeh21cVItVYRRiQvxXcYBeRl2ASWfR872kp+Px0jcCnN9GxBZXduAYpr1rCyHjwJPHpoEnyxumpDrMhFjbGF1ZGUtc29ubmV0LTQtNjgAQgh0aGlua2luZxIMTMKJ5FsmJvO3wTAlGgwDc4/h03lzbzoyCQ8iMJOzqCCUiZrPffqDbNi14bcpSRvtknCv1puasa3hemMYPA7p+uuvmhPUgYjqpj97uSpIyD8S0b6dUmgvBwjwRDdiQMOEGW76VVE59x7A2AH++HfA+F41v6t9i+tV39uGPkDAgo1ZXaK9AsKYx78ahgAf2YCdKYgvOgwiGAE="}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":3,"cache_creation_input_tokens":13101,"cache_read_input_tokens":16099,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":13101},"output_tokens":1,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"27786795-8271-4501-973e-0c5bf78c8a54","request_id":"req_011Ccf91CKgBHFrDejdGreGT"}\n'
TEXT_BLOCK = b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01QotPaa8Cum5JvUGQio2xGS","type":"message","role":"assistant","content":[{"type":"text","text":"Claiming the next task."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":3,"cache_creation_input_tokens":13101,"cache_read_input_tokens":16099,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":13101},"output_tokens":1,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"b8bd4b7c-51e9-4758-8cc3-392a67a53667","request_id":"req_011Ccf91CKgBHFrDejdGreGT"}\n'
TOOL_USE_BASH = b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01QotPaa8Cum5JvUGQio2xGS","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_01G9oRbpKPZ5VE1fd12eAgpw","name":"Bash","input":{"command":"tg claim coder","description":"Claim next coder task"},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":3,"cache_creation_input_tokens":13101,"cache_read_input_tokens":16099,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":13101},"output_tokens":1,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"69df2580-09f3-4e37-b15e-a7960d4e9e84","request_id":"req_011Ccf91CKgBHFrDejdGreGT"}\n'
RATE_LIMIT = b'{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1783092600,"rateLimitType":"five_hour","overageStatus":"rejected","overageDisabledReason":"out_of_credits","isUsingOverage":false},"uuid":"7e9c148d-6e66-4a1e-b133-bbba9c670cdb","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
API_RETRY = b'{"type":"system","subtype":"api_retry","attempt":1,"max_retries":10,"retry_delay_ms":523.1822743430553,"error_status":null,"error":"unknown","session_id":"da66f5e5-fccc-45cc-b50b-cd942aba9654","uuid":"625be3ac-d5c2-4237-8b43-8b6224f91fb7"}\n'
TASK_STARTED = b'{"type":"system","subtype":"task_started","task_id":"btzdmo0d4","tool_use_id":"toolu_01G9oRbpKPZ5VE1fd12eAgpw","description":"Claim next coder task","task_type":"local_bash","uuid":"aa7046b4-0fc6-4635-a102-4c5d47d25e9b","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
TASK_NOTIFICATION = b'{"type":"system","subtype":"task_notification","task_id":"btzdmo0d4","tool_use_id":"toolu_01G9oRbpKPZ5VE1fd12eAgpw","status":"completed","output_file":"","summary":"Claim next coder task","uuid":"2790bdb9-964c-4ee0-a4b9-538208e17deb","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea"}\n'
TOOL_RESULT_FALSE = b'{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_01G9oRbpKPZ5VE1fd12eAgpw","type":"tool_result","content":"{\\n  \\"id\\": \\"afo.1\\",\\n  \\"title\\": \\"build: GRID-047-coder-commit-subject-convention\\",\\n  \\"type\\": \\"task\\",\\n  \\"parent\\": \\"afo\\",\\n  \\"role\\": \\"coder\\",\\n  \\"step\\": \\"build\\",\\n  \\"status\\": \\"in-progress\\",\\n  \\"project\\": null,\\n  \\"goal\\": null,\\n  \\"artifacts\\": [],\\n  \\"description\\": null,\\n  \\"needs\\": null,\\n  \\"outcome\\": null,\\n  \\"deps\\": 1,\\n  \\"notes\\": null,\\n  \\"epic\\": null,\\n  \\"attention\\": false,\\n  \\"since\\": null,\\n  \\"fired_at\\": null,\\n  \\"story_artifacts\\": [\\n    {\\n      \\"type\\": \\"spec\\",\\n      \\"value\\": \\"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md\\"\\n    },\\n    {\\n      \\"type\\": \\"repo\\",\\n      \\"value\\": \\"the-grid\\"\\n    }\\n  ],\\n  \\"workspace\\": \\"/Users/kenmclennan/workspace/projects/the-grid/.worktrees/afo\\",\\n  \\"branch\\": \\"feat/grid-047-coder-commit-subject-convention\\",\\n  \\"spec_path\\": \\"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md\\"\\n}","is_error":false}]},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"47fddce6-dce5-4f5c-81e0-60feb900bbe2","timestamp":"2026-07-03T12:40:04.686Z","tool_use_result":{"stdout":"{\\n  \\"id\\": \\"afo.1\\",\\n  \\"title\\": \\"build: GRID-047-coder-commit-subject-convention\\",\\n  \\"type\\": \\"task\\",\\n  \\"parent\\": \\"afo\\",\\n  \\"role\\": \\"coder\\",\\n  \\"step\\": \\"build\\",\\n  \\"status\\": \\"in-progress\\",\\n  \\"project\\": null,\\n  \\"goal\\": null,\\n  \\"artifacts\\": [],\\n  \\"description\\": null,\\n  \\"needs\\": null,\\n  \\"outcome\\": null,\\n  \\"deps\\": 1,\\n  \\"notes\\": null,\\n  \\"epic\\": null,\\n  \\"attention\\": false,\\n  \\"since\\": null,\\n  \\"fired_at\\": null,\\n  \\"story_artifacts\\": [\\n    {\\n      \\"type\\": \\"spec\\",\\n      \\"value\\": \\"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md\\"\\n    },\\n    {\\n      \\"type\\": \\"repo\\",\\n      \\"value\\": \\"the-grid\\"\\n    }\\n  ],\\n  \\"workspace\\": \\"/Users/kenmclennan/workspace/projects/the-grid/.worktrees/afo\\",\\n  \\"branch\\": \\"feat/grid-047-coder-commit-subject-convention\\",\\n  \\"spec_path\\": \\"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md\\"\\n}","stderr":"","interrupted":false,"isImage":false,"noOutputExpected":false}}\n'
TOOL_USE_READ = b'{"type":"assistant","message":{"model":"claude-sonnet-4-6","id":"msg_01TP3GXg1z13vddyMgSah4bj","type":"message","role":"assistant","content":[{"type":"tool_use","id":"toolu_01GejtypxUQeUhutowvTxjCX","name":"Read","input":{"file_path":"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md"},"caller":{"type":"direct"}}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":1,"cache_creation_input_tokens":462,"cache_read_input_tokens":29200,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":462},"output_tokens":66,"service_tier":"standard","inference_geo":"not_available"},"diagnostics":null,"context_management":null},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"cbc34992-f5f1-4910-8ffd-22a2acf68e6b","request_id":"req_011Ccf93TBgu9bFcpJqXpS5U"}\n'
TOOL_RESULT_OMITTED = b'{"type":"user","message":{"role":"user","content":[{"tool_use_id":"toolu_01GejtypxUQeUhutowvTxjCX","type":"tool_result","content":"1\\t# GRID-047: coder commit subject convention (feeds the PR title)\\n2\\t\\n3\\tThe PR title is derived from the branch\'s commit subject (`gh` uses it), and `open-pr` now\\n4\\tappends the spec id for traceability (`<subject> (<SPEC-ID>)`). For that to read consistently,\\n5\\tthe coder\'s commit **subject** needs a consistent shape. Today it is ad hoc, so PR titles vary in\\n6\\tform. This adds the one convention to `coder.md`.\\n7\\t\\n8\\tThe convention lives in the workflow step (not a per-project `CLAUDE.md`), so it travels to every\\n9\\trepo the-grid drives - the same reason `open-pr` owns the spec-id append.\\n10\\t\\n11\\t## Change\\n12\\t\\n13\\t`steps/coder.md` step 6 (the squashed commit): specify the subject format.\\n14\\t\\n15\\t- Subject: `<type>(<scope>): <imperative summary>`\\n16\\t  - `type`: conventional-commit - `feat` / `fix` / `chore` / `refactor` / `test` / `docs`\\n17\\t  - `scope`: the touched area (e.g. `config`, `run`, `store`, `flow`); omit when it spans many\\n18\\t  - `summary`: imperative, concise, hyphens not emdashes\\n19\\t- Do NOT put the spec id in the subject - `open-pr` appends it, so the coder must not duplicate it.\\n20\\t- The commit body/footer conventions (Co-Authored-By, etc.) are unchanged, per the repo\'s\\n21\\t  `CLAUDE.md`.\\n22\\t\\n23\\t## Acceptance criteria\\n24\\t\\n25\\t- `steps/coder.md` step 6 states the `<type>(<scope>): <summary>` subject format, notes hyphens\\n26\\t  not emdashes, and notes that `open-pr` appends the spec id (so the coder does not).\\n27\\t- No other step or engine change; this is a single-brief edit.\\n28\\t- `bash tests/run.sh` green; `uv run ruff check .` clean. No comments/docstrings added.\\n29\\t\\n30\\t## Out of scope\\n31\\t\\n32\\t- The `open-pr` spec-id append (already shipped by hand).\\n33\\t- Enforcing/validating the format in code (it is brief guidance, like the rest of the coder\'s\\n34\\t  craft; the reviewer and PR title surface deviations).\\n35\\t- Commit body format beyond the subject.\\n36\\t"}]},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"e259e05e-dd96-49f5-a4f2-b6af176da9da","timestamp":"2026-07-03T12:40:08.883Z","tool_use_result":{"type":"text","file":{"filePath":"/Users/kenmclennan/workspace/specs/GRID-047-coder-commit-subject-convention.md","content":"# GRID-047: coder commit subject convention (feeds the PR title)\\n\\nThe PR title is derived from the branch\'s commit subject (`gh` uses it), and `open-pr` now\\nappends the spec id for traceability (`<subject> (<SPEC-ID>)`). For that to read consistently,\\nthe coder\'s commit **subject** needs a consistent shape. Today it is ad hoc, so PR titles vary in\\nform. This adds the one convention to `coder.md`.\\n\\nThe convention lives in the workflow step (not a per-project `CLAUDE.md`), so it travels to every\\nrepo the-grid drives - the same reason `open-pr` owns the spec-id append.\\n\\n## Change\\n\\n`steps/coder.md` step 6 (the squashed commit): specify the subject format.\\n\\n- Subject: `<type>(<scope>): <imperative summary>`\\n  - `type`: conventional-commit - `feat` / `fix` / `chore` / `refactor` / `test` / `docs`\\n  - `scope`: the touched area (e.g. `config`, `run`, `store`, `flow`); omit when it spans many\\n  - `summary`: imperative, concise, hyphens not emdashes\\n- Do NOT put the spec id in the subject - `open-pr` appends it, so the coder must not duplicate it.\\n- The commit body/footer conventions (Co-Authored-By, etc.) are unchanged, per the repo\'s\\n  `CLAUDE.md`.\\n\\n## Acceptance criteria\\n\\n- `steps/coder.md` step 6 states the `<type>(<scope>): <summary>` subject format, notes hyphens\\n  not emdashes, and notes that `open-pr` appends the spec id (so the coder does not).\\n- No other step or engine change; this is a single-brief edit.\\n- `bash tests/run.sh` green; `uv run ruff check .` clean. No comments/docstrings added.\\n\\n## Out of scope\\n\\n- The `open-pr` spec-id append (already shipped by hand).\\n- Enforcing/validating the format in code (it is brief guidance, like the rest of the coder\'s\\n  craft; the reviewer and PR title surface deviations).\\n- Commit body format beyond the subject.\\n","numLines":36,"startLine":1,"totalLines":36}}}\n'
TOOL_RESULT_TRUE = b'{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"The user doesn\'t want to proceed with this tool use. The tool use was rejected (eg. if it was a file edit, the new_string was NOT written to the file). STOP what you are doing and wait for the user to tell you how to proceed.\\n\\nNote: The user\'s next message may contain a correction or preference. Pay close attention \xe2\x80\x94 if they explain what went wrong or how they\'d prefer you to work, consider saving that to memory for future sessions.","is_error":true,"tool_use_id":"toolu_01VeQPiaVcDGUsuKwDhVgm9E"}]},"parent_tool_use_id":null,"session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","uuid":"d841d4f5-1499-45f8-8923-95f2a50f09f1","timestamp":"2026-07-03T12:44:36.890Z","tool_use_result":"User rejected tool use"}\n'
RESULT_EVENT = b'{"type":"result","subtype":"error_during_execution","duration_ms":303278,"duration_api_ms":42769,"is_error":true,"num_turns":12,"stop_reason":"tool_use","session_id":"7c5f0968-d6de-4df9-b07f-7cdb41e507ea","total_cost_usd":0.2358519,"usage":{"input_tokens":12,"cache_creation_input_tokens":19456,"cache_read_input_tokens":315283,"output_tokens":1633,"server_tool_use":{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard","cache_creation":{"ephemeral_1h_input_tokens":19456,"ephemeral_5m_input_tokens":0},"inference_geo":"not_available","iterations":[{"input_tokens":1,"output_tokens":169,"cache_read_input_tokens":35377,"cache_creation_input_tokens":178,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":178},"type":"message"}],"speed":"standard"},"modelUsage":{"claude-sonnet-4-6":{"inputTokens":12,"outputTokens":1633,"cacheReadInputTokens":315283,"cacheCreationInputTokens":19456,"webSearchRequests":0,"costUSD":0.2358519,"contextWindow":200000,"maxOutputTokens":32000}},"permission_denials":[],"terminal_reason":"aborted_tools","fast_mode_state":"off","uuid":"71b6f38e-0e3c-4243-94b7-a4e226020aef","errors":["[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=tool_use"]}\n'
TRUNCATED_LINE_PREFIX = '{"type":"assistant","message":{"model":"claude-sonnet-4-6","'
TRUNCATED_LINE = (TRUNCATED_LINE_PREFIX + "\n").encode()

EXCERPT = (
    HOOK_STARTED + HOOK_RESPONSE + SYSTEM_INIT + THINKING_TOKENS + THINKING_BLOCK + TEXT_BLOCK
    + TOOL_USE_BASH + RATE_LIMIT + API_RETRY + TASK_STARTED + TASK_NOTIFICATION + TOOL_RESULT_FALSE
    + TOOL_USE_READ + TOOL_RESULT_OMITTED + TOOL_RESULT_TRUE + RESULT_EVENT + TRUNCATED_LINE
)


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


class RealCaptureKindMappingTest(unittest.TestCase):
    def setUp(self):
        self.lines = LogLineParser().feed(EXCERPT)

    def test_line_count_matches_every_row_of_the_kind_table(self):
        self.assertEqual(len(self.lines), 16)

    def test_thinking_tokens_produces_no_line(self):
        kinds = [line.kind for line in self.lines]
        self.assertEqual(kinds.count(LogKind.THINKING), 1)

    def test_thinking_block_maps_to_thinking_full_text(self):
        line = self.lines[3]
        self.assertEqual(line.kind, LogKind.THINKING)
        self.assertEqual(line.text, "Let me start by claiming a task using `tg claim coder`.")

    def test_text_block_maps_to_text(self):
        line = self.lines[4]
        self.assertEqual(line.kind, LogKind.TEXT)
        self.assertEqual(line.text, "Claiming the next task.")

    def test_bash_tool_use_maps_to_tool_with_command(self):
        line = self.lines[5]
        self.assertEqual(line.kind, LogKind.TOOL)
        self.assertEqual(line.text, "$ tg claim coder")

    def test_non_bash_tool_use_maps_to_tool_with_salient_input(self):
        line = self.lines[11]
        self.assertEqual(line.kind, LogKind.TOOL)
        self.assertIn("Read", line.text)
        self.assertIn("GRID-047-coder-commit-subject-convention.md", line.text)

    def test_rate_limit_event_maps_to_retry(self):
        line = self.lines[6]
        self.assertEqual(line.kind, LogKind.RETRY)
        self.assertIn("allowed", line.text)

    def test_api_retry_maps_to_retry(self):
        line = self.lines[7]
        self.assertEqual(line.kind, LogKind.RETRY)
        self.assertIn("unknown", line.text)

    def test_task_started_maps_to_system(self):
        line = self.lines[8]
        self.assertEqual(line.kind, LogKind.SYSTEM)

    def test_task_lifecycle_subtype_maps_to_progress(self):
        line = self.lines[9]
        self.assertEqual(line.kind, LogKind.PROGRESS)
        self.assertEqual(line.text, "Claim next coder task")

    def test_tool_result_is_error_false_carries_full_untruncated_content(self):
        line = self.lines[10]
        self.assertEqual(line.kind, LogKind.RESULT)
        self.assertFalse(line.text.startswith("[error]"))
        self.assertIn("afo.1", line.text)
        self.assertIn("spec_path", line.text)

    def test_tool_result_is_error_omitted_carries_full_content(self):
        line = self.lines[12]
        self.assertEqual(line.kind, LogKind.RESULT)
        self.assertFalse(line.text.startswith("[error]"))
        self.assertIn("GRID-047", line.text)
        self.assertIn("Commit body format beyond the subject.", line.text)

    def test_tool_result_is_error_true_is_marked(self):
        line = self.lines[13]
        self.assertEqual(line.kind, LogKind.RESULT)
        self.assertTrue(line.text.startswith("[error]"))
        self.assertIn("STOP what you are doing", line.text)

    def test_top_level_result_event_maps_to_system(self):
        line = self.lines[14]
        self.assertEqual(line.kind, LogKind.SYSTEM)
        self.assertIn("aborted_tools", line.text)

    def test_truncated_line_becomes_its_own_unparsed_line(self):
        line = self.lines[15]
        self.assertEqual(line.kind, LogKind.UNPARSED)
        self.assertEqual(line.text, TRUNCATED_LINE_PREFIX)

    def test_hook_and_init_events_map_to_system(self):
        self.assertEqual(self.lines[0].kind, LogKind.SYSTEM)
        self.assertEqual(self.lines[1].kind, LogKind.SYSTEM)
        self.assertEqual(self.lines[2].kind, LogKind.SYSTEM)


class RealCaptureTimestampTest(unittest.TestCase):
    def setUp(self):
        self.lines = LogLineParser().feed(EXCERPT)

    def test_leading_run_before_any_timestamp_shows_none(self):
        for line in self.lines[:10]:
            self.assertIsNone(line.timestamp)

    def test_first_timestamped_event_carries_its_own_timestamp(self):
        self.assertEqual(self.lines[10].timestamp, _ts("2026-07-03T12:40:04.686Z"))

    def test_untimestamped_event_inherits_the_previous_real_timestamp(self):
        self.assertEqual(self.lines[11].timestamp, self.lines[10].timestamp)

    def test_a_later_timestamped_event_updates_what_is_inherited(self):
        self.assertEqual(self.lines[12].timestamp, _ts("2026-07-03T12:40:08.883Z"))
        self.assertNotEqual(self.lines[12].timestamp, self.lines[10].timestamp)

    def test_system_kind_lines_always_inherit_even_with_a_recent_real_timestamp(self):
        self.assertEqual(self.lines[13].timestamp, _ts("2026-07-03T12:44:36.890Z"))
        self.assertEqual(self.lines[14].timestamp, self.lines[13].timestamp)

    def test_unparsed_line_inherits_too(self):
        self.assertEqual(self.lines[15].timestamp, self.lines[14].timestamp)


class ForwardCompatibilityTest(unittest.TestCase):
    def test_unrecognised_system_subtype_defaults_to_system_not_dropped(self):
        raw = b'{"type":"system","subtype":"a_future_subtype_nobody_has_seen_yet","uuid":"x"}\n'
        lines = LogLineParser().feed(raw)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].kind, LogKind.SYSTEM)

    def test_unrecognised_top_level_type_defaults_to_system_not_dropped(self):
        raw = b'{"type":"a_future_event_type_nobody_has_seen_yet","foo":"bar"}\n'
        lines = LogLineParser().feed(raw)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].kind, LogKind.SYSTEM)


class BlankAndMalformedLineTest(unittest.TestCase):
    def test_blank_line_produces_nothing(self):
        self.assertEqual(LogLineParser().feed(b"\n"), [])

    def test_whitespace_only_line_produces_nothing(self):
        self.assertEqual(LogLineParser().feed(b"   \n"), [])

    def test_malformed_json_becomes_its_own_unparsed_line(self):
        lines = LogLineParser().feed(TRUNCATED_LINE)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].kind, LogKind.UNPARSED)
        self.assertEqual(lines[0].text, TRUNCATED_LINE_PREFIX)


class PartialLineBufferingTest(unittest.TestCase):
    def test_a_line_split_mid_object_across_two_feeds_parses_as_one_line(self):
        parser = LogLineParser()
        first_chunk = b'{"type": "assistant", "mess'
        second_chunk = b'age": {"content": [{"type": "text", "text": "hello"}]}}\n'

        first = parser.feed(first_chunk)

        self.assertEqual(first, [])

        second = parser.feed(second_chunk)

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].kind, LogKind.TEXT)
        self.assertEqual(second[0].text, "hello")

    def test_unbuffered_feeding_of_the_same_split_would_have_failed(self):
        first_chunk = b'{"type": "assistant", "mess'
        second_chunk = b'age": {"content": [{"type": "text", "text": "hello"}]}}\n'

        naive_first = LogLineParser().feed(first_chunk + b"\n")
        naive_second = LogLineParser().feed(second_chunk)

        self.assertEqual(naive_first[0].kind, LogKind.UNPARSED)
        self.assertEqual(naive_second[0].kind, LogKind.UNPARSED)


if __name__ == "__main__":
    unittest.main()
