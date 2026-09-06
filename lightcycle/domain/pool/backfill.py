import json
import re
from itertools import islice
from typing import Optional

_ID_PATTERN = r"[A-Za-z][A-Za-z0-9]*-[\w.]+"
_ID_KEY_RE = re.compile(r'"id"\s*:\s*"(%s)"' % _ID_PATTERN)
_ID_VALUE_RE = re.compile(r"^%s$" % _ID_PATTERN)


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
