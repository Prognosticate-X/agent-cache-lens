"""
Canonical serialization and prefix hashing engine for LLM Prompt Caches.
Provides byte-exact deterministic representations across Python / Node runtimes.
"""

import json
import hashlib
from typing import Any, Dict, List, Optional, Tuple, Union


def canonical_serialize(obj: Any) -> str:
    """
    Recursively serialize an arbitrary JSON-compatible object into a
    strictly deterministic, canonical byte representation.
    - All dictionary keys are sorted recursively.
    - Separators are stripped of whitespace (',', ':').
    - Unicode characters are preserved without ASCII escaping.
    """
    if isinstance(obj, dict):
        # Sort keys lexicographically and canonicalize child values
        sorted_dict = {k: canonical_serialize(obj[k]) for k in sorted(obj.keys())}
        # Re-pack to standard json
        parts = [f"{json.dumps(k, ensure_ascii=False)}:{v}" for k, v in sorted_dict.items()]
        return "{" + ",".join(parts) + "}"
    elif isinstance(obj, list):
        items = [canonical_serialize(item) for item in obj]
        return "[" + ",".join(items) + "]"
    else:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def compute_sha256(text_or_bytes: Union[str, bytes]) -> str:
    """Compute standard SHA-256 hexadecimal hash."""
    if isinstance(text_or_bytes, str):
        data = text_or_bytes.encode('utf-8')
    else:
        data = text_or_bytes
    return hashlib.sha256(data).hexdigest()


def estimate_token_count(text: str) -> int:
    """
    Fast, zero-dependency token count estimator.
    Approximates BPE tokenizers (~3.8 chars per English token, 1.5 chars per CJK character).
    """
    if not text:
        return 0
    cjk_count = 0
    ascii_count = 0
    for char in text:
        if ord(char) > 127:
            cjk_count += 1
        else:
            ascii_count += 1
    # Standard rule of thumb: ~3.8 ascii chars / token, ~1.5 CJK char / token
    tokens = int(ascii_count / 3.8) + int(cjk_count / 1.5)
    return max(1, tokens)


class PrefixSegment:
    """Represents a discrete cacheable segment in the wire payload."""
    def __init__(self, segment_type: str, name: str, content: Any, has_cache_control: bool = False):
        self.segment_type = segment_type  # 'system', 'tool', 'message'
        self.name = name                  # identifier or index
        self.raw_content = content
        self.canonical_str = canonical_serialize(content)
        self.byte_length = len(self.canonical_str.encode('utf-8'))
        self.estimated_tokens = estimate_token_count(self.canonical_str)
        self.has_cache_control = has_cache_control
        self.hash = compute_sha256(self.canonical_str)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.segment_type,
            "name": self.name,
            "has_cache_control": self.has_cache_control,
            "byte_length": self.byte_length,
            "estimated_tokens": self.estimated_tokens,
            "hash": self.hash[:16]
        }


def extract_segments(payload: Dict[str, Any]) -> List[PrefixSegment]:
    """
    Deconstructs an Anthropic or OpenAI API payload into sequential prefix segments.
    Preserves exact sequence order as evaluated by the model provider.
    """
    segments: List[PrefixSegment] = []

    # 1. System Prompt
    system = payload.get("system")
    if system is not None:
        if isinstance(system, list):
            for idx, block in enumerate(system):
                has_cc = isinstance(block, dict) and "cache_control" in block
                segments.append(PrefixSegment("system", f"system_block_{idx}", block, has_cache_control=has_cc))
        else:
            segments.append(PrefixSegment("system", "system_text", system))

    # 2. Tool Definitions
    tools = payload.get("tools")
    if tools and isinstance(tools, list):
        for idx, tool in enumerate(tools):
            tool_name = tool.get("name", f"tool_{idx}") if isinstance(tool, dict) else f"tool_{idx}"
            has_cc = isinstance(tool, dict) and "cache_control" in tool
            segments.append(PrefixSegment("tool", f"tool:{tool_name}", tool, has_cache_control=has_cc))

    # 3. Message turns
    messages = payload.get("messages")
    if messages and isinstance(messages, list):
        for idx, msg in enumerate(messages):
            role = msg.get("role", "unknown") if isinstance(msg, dict) else "unknown"
            has_cc = False
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and "cache_control" in b:
                            has_cc = True
                            break
            segments.append(PrefixSegment("message", f"turn_{idx}:{role}", msg, has_cache_control=has_cc))

    return segments
