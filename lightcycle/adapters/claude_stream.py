import json
import re
from itertools import islice
from typing import Optional

from lightcycle.domain.money import Cost
from lightcycle.domain.pool.attribution import AttributionEvent, ToolUsage
from lightcycle.domain.pool.rate_limit import RateLimitEvent
from lightcycle.domain.pool.usage import UsageEvent
from lightcycle.domain.pool.worker_session import is_terminal_command
from lightcycle.ports.claude_stream import ClaudeStreamPort

_ID_PATTERN = r"[A-Za-z][A-Za-z0-9]*-[\w.]+"
_ID_KEY_RE = re.compile(r'"id"\s*:\s*"(%s)"' % _ID_PATTERN)
_ID_VALUE_RE = re.compile(r"^%s$" % _ID_PATTERN)


def parse_usage_event(lines) -> UsageEvent:
    found = UsageEvent()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "result":
            continue
        found = _from_model_usage(data.get("modelUsage") or {})
    return found


def _from_model_usage(model_usage) -> UsageEvent:
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    cost_usd = 0.0
    cost_basis = None
    thinking_tokens = None
    for entry in model_usage.values():
        input_tokens += entry.get("inputTokens") or 0
        output_tokens += entry.get("outputTokens") or 0
        cache_read_tokens += entry.get("cacheReadInputTokens") or 0
        cache_creation_tokens += entry.get("cacheCreationInputTokens") or 0
        cost_usd += entry.get("costUSD") or 0.0
        if cost_basis is None and "costBasis" in entry:
            cost_basis = entry["costBasis"]
        if "thinkingTokens" in entry:
            thinking_tokens = (thinking_tokens or 0) + entry["thinkingTokens"]
    return UsageEvent(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cost_usd=Cost.from_usd(cost_usd),
        cost_basis=cost_basis,
        thinking_tokens=thinking_tokens,
        has_result_line=True,
    )


def _content_bytes(content):
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content.encode("utf-8"))
    if isinstance(content, list):
        text = "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
        return len(text.encode("utf-8"))
    return 0


def parse_attribution_chunk(lines, seen_message_ids, pending_tool_use):
    message_ids = set(seen_message_ids)
    new_message_ids = set()
    usage_by_id = {}
    tool_names = dict(pending_tool_use)
    tool_usage = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        content_blocks = (data.get("message") or {}).get("content") or []
        if data.get("type") == "assistant":
            message_id = (data.get("message") or {}).get("id")
            if message_id and message_id not in message_ids:
                message_ids.add(message_id)
                new_message_ids.add(message_id)
                usage_by_id[message_id] = (data.get("message") or {}).get("usage") or {}
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_names[block.get("id")] = block.get("name")
        elif data.get("type") == "user":
            for block in content_blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                name = tool_names.pop(block.get("tool_use_id"), "unknown")
                usage = tool_usage.setdefault(name, ToolUsage())
                tool_usage[name] = ToolUsage(
                    calls=usage.calls + 1,
                    bytes=usage.bytes + _content_bytes(block.get("content")),
                )
    recovered_input_tokens = 0
    recovered_output_tokens = 0
    recovered_cache_read_tokens = 0
    recovered_cache_creation_tokens = 0
    for message_usage in usage_by_id.values():
        recovered_input_tokens += message_usage.get("input_tokens") or 0
        recovered_output_tokens += message_usage.get("output_tokens") or 0
        recovered_cache_read_tokens += message_usage.get("cache_read_input_tokens") or 0
        recovered_cache_creation_tokens += message_usage.get("cache_creation_input_tokens") or 0
    delta = AttributionEvent(
        turn_count=len(new_message_ids),
        tool_usage=tool_usage,
        recovered_input_tokens=recovered_input_tokens,
        recovered_output_tokens=recovered_output_tokens,
        recovered_cache_read_tokens=recovered_cache_read_tokens,
        recovered_cache_creation_tokens=recovered_cache_creation_tokens,
    )
    return delta, message_ids, tool_names


def parse_attribution_event(lines) -> AttributionEvent:
    return parse_attribution_chunk(lines, set(), {})[0]


def parse_rate_limit_event(lines) -> Optional[RateLimitEvent]:
    found = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "rate_limit_event":
            continue
        info = data.get("rate_limit_info") or {}
        status = info.get("status")
        if not status:
            continue
        found = RateLimitEvent(status=status, reset_at=info.get("resetsAt"))
    return found


def _content_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return ""


def _recover_id(text):
    try:
        parsed = json.loads(text)
    except ValueError:
        match = _ID_KEY_RE.search(text)
        return match.group(1) if match else None
    if isinstance(parsed, dict):
        value = parsed.get("id")
        if isinstance(value, str) and _ID_VALUE_RE.match(value):
            return value
    return None


def extract_claimed_step(lines, limit=60) -> Optional[str]:
    claim_ids = set()
    for line in islice(lines, limit):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        content_blocks = (data.get("message") or {}).get("content") or []
        if data.get("type") == "assistant":
            for block in content_blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") != "Bash":
                    continue
                command = (block.get("input") or {}).get("command") or ""
                if "lc claim" in command.strip():
                    claim_ids.add(block.get("id"))
        elif data.get("type") == "user":
            for block in content_blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("tool_use_id") not in claim_ids:
                    continue
                recovered = _recover_id(_content_text(block.get("content")))
                if recovered:
                    return recovered
    return None


def saw_terminal_command(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        for c in data.get("message", {}).get("content", []) or []:
            if c.get("type") == "tool_use":
                cmd = str((c.get("input") or {}).get("command", ""))
                if is_terminal_command(cmd):
                    return True
    return False


def saw_session_activity(lines):
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") in ("assistant", "result"):
            return True
    return False


class ClaudeStreamAdapter(ClaudeStreamPort):
    def parse_usage_event(self, lines):
        return parse_usage_event(lines)

    def parse_attribution_event(self, lines):
        return parse_attribution_event(lines)

    def parse_attribution_chunk(self, lines, seen_message_ids, pending_tool_use):
        return parse_attribution_chunk(lines, seen_message_ids, pending_tool_use)

    def parse_rate_limit_event(self, lines):
        return parse_rate_limit_event(lines)

    def extract_claimed_step(self, lines, limit=60):
        return extract_claimed_step(lines, limit)

    def saw_terminal_command(self, lines):
        return saw_terminal_command(lines)

    def saw_session_activity(self, lines):
        return saw_session_activity(lines)
