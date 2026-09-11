from dataclasses import dataclass, field
from types import MappingProxyType
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

    def __post_init__(self):
        object.__setattr__(self, "tool_usage", MappingProxyType(dict(self.tool_usage)))


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
