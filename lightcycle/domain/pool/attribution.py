import json
from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class ToolUsage:
    calls: int = 0
    bytes: int = 0


@dataclass(frozen=True)
class AttributionEvent:
    turn_count: int = 0
    tool_usage: Dict[str, ToolUsage] = field(default_factory=dict)
    recovered_input_tokens: int = 0
    recovered_output_tokens: int = 0
    recovered_cache_read_tokens: int = 0
    recovered_cache_creation_tokens: int = 0


def sum_attribution_events(events):
    turn_count = 0
    tool_usage = {}
    for event in events:
        turn_count += event.turn_count
        for tool, usage in event.tool_usage.items():
            existing = tool_usage.get(tool, ToolUsage())
            tool_usage[tool] = ToolUsage(
                calls=existing.calls + usage.calls, bytes=existing.bytes + usage.bytes
            )
    return turn_count, tool_usage


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
