"""
Forensic divergence inspector between consecutive conversation turns or framework runs.
Pinpoints the exact byte, key, or block that caused prompt cache invalidation.
"""

import difflib
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from .hasher import PrefixSegment, extract_segments, canonical_serialize, compute_sha256


class InvalidationReason(str, Enum):
    NONE = "NONE"                                       # Cache prefix intact
    SYSTEM_MUTATION = "SYSTEM_MUTATION"                 # System prompt modified (e.g., timestamps/flags)
    TOOL_SCHEMA_KEY_DRIFT = "TOOL_SCHEMA_KEY_DRIFT"     # Tool keys reordered without semantic change
    TOOL_SET_ALTERATION = "TOOL_SET_ALTERATION"         # Tools added/removed mid-session (e.g., skill load)
    COMPACTION_COLLAPSE = "COMPACTION_COLLAPSE"         # Context summarized or truncated early
    HISTORY_MUTATION = "HISTORY_MUTATION"               # Historical message edited in-place
    BREAKPOINT_MISPLACEMENT = "BREAKPOINT_MISPLACEMENT" # Missing or shifted ephemeral breakpoint
    NEW_TURN_GROWTH = "NEW_TURN_GROWTH"                 # Normal growth (divergence at the tail only)


class DivergenceReport:
    """Detailed forensic analysis of cache prefix divergence between two turns."""
    def __init__(
        self,
        reason: InvalidationReason,
        diverged_segment_index: int,
        segment_name: str,
        matched_tokens: int,
        lost_tokens: int,
        total_tokens_prev: int,
        total_tokens_curr: int,
        details: str,
        diff_snippet: Optional[str] = None
    ):
        self.reason = reason
        self.diverged_segment_index = diverged_segment_index
        self.segment_name = segment_name
        self.matched_tokens = matched_tokens
        self.lost_tokens = lost_tokens
        self.total_tokens_prev = total_tokens_prev
        self.total_tokens_curr = total_tokens_curr
        self.details = details
        self.diff_snippet = diff_snippet

    @property
    def cache_retention_ratio(self) -> float:
        """Percentage of prior context successfully retained in cache."""
        if self.total_tokens_prev <= 0:
            return 1.0
        return min(1.0, max(0.0, self.matched_tokens / self.total_tokens_prev))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason.value,
            "diverged_segment_index": self.diverged_segment_index,
            "segment_name": self.segment_name,
            "matched_tokens": self.matched_tokens,
            "lost_tokens": self.lost_tokens,
            "cache_retention_ratio": round(self.cache_retention_ratio, 4),
            "total_tokens_prev": self.total_tokens_prev,
            "total_tokens_curr": self.total_tokens_curr,
            "details": self.details,
            "diff_snippet": self.diff_snippet
        }


def find_text_diff_snippet(str_a: str, str_b: str, max_lines: int = 10) -> str:
    """Generate a clean unified diff highlighting the exact point of deviation."""
    lines_a = str_a.splitlines(keepends=True)
    lines_b = str_b.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile="Turn N-1", tofile="Turn N", n=2))
    if not diff:
        # Check character-by-character divergence for single line strings
        for i, (ca, cb) in enumerate(zip(str_a, str_b)):
            if ca != cb:
                start = max(0, i - 25)
                end = min(len(str_a), i + 25)
                return f"Char mismatch at offset {i}:\n  Prev: ...{str_a[start:end]}...\n  Curr: ...{str_b[start:end]}..."
        return f"Length mismatch (prev: {len(str_a)} chars, curr: {len(str_b)} chars)"
    return "".join(diff[:max_lines])


def analyze_divergence(payload_a: Dict[str, Any], payload_b: Dict[str, Any]) -> DivergenceReport:
    """
    Compares two sequential API payloads (payload_a = Turn N-1, payload_b = Turn N)
    and pinpoints the exact cause of any prompt cache prefix invalidation.
    """
    segs_a = extract_segments(payload_a)
    segs_b = extract_segments(payload_b)

    tokens_a = sum(s.estimated_tokens for s in segs_a)
    tokens_b = sum(s.estimated_tokens for s in segs_b)

    # Walk segments in sequential order
    matched_tokens = 0
    diverged_idx = -1
    diverged_name = ""

    min_len = min(len(segs_a), len(segs_b))

    for i in range(min_len):
        sa = segs_a[i]
        sb = segs_b[i]

        if sa.hash == sb.hash:
            matched_tokens += sa.estimated_tokens
        else:
            diverged_idx = i
            diverged_name = sb.name
            break

    # Scenario 1: Clean prefix match up to the end of segs_a
    if diverged_idx == -1:
        if len(segs_b) >= len(segs_a):
            # Normal append of new message turns
            new_tokens = sum(s.estimated_tokens for s in segs_b[min_len:])
            return DivergenceReport(
                reason=InvalidationReason.NEW_TURN_GROWTH,
                diverged_segment_index=min_len,
                segment_name="new_turn_tail",
                matched_tokens=matched_tokens,
                lost_tokens=0,
                total_tokens_prev=tokens_a,
                total_tokens_curr=tokens_b,
                details=f"Prefix preserved perfectly ({matched_tokens} tokens cached). Tail appended {new_tokens} tokens."
            )
        else:
            # segs_b is SHORTER than segs_a while matching prefix -> Compaction/Truncation occurred!
            lost_tokens = tokens_a - matched_tokens
            return DivergenceReport(
                reason=InvalidationReason.COMPACTION_COLLAPSE,
                diverged_segment_index=len(segs_b),
                segment_name="tail_truncated",
                matched_tokens=matched_tokens,
                lost_tokens=lost_tokens,
                total_tokens_prev=tokens_a,
                total_tokens_curr=tokens_b,
                details=f"Conversation was truncated or compacted. Prior turn had {len(segs_a)} segments, current has {len(segs_b)}."
            )

    # Scenario 2: Divergence occurred within 0 .. min_len - 1
    sa = segs_a[diverged_idx]
    sb = segs_b[diverged_idx]
    lost_tokens = tokens_a - matched_tokens

    # Diagnose specific reason
    reason = InvalidationReason.HISTORY_MUTATION
    diff_text = find_text_diff_snippet(sa.canonical_str, sb.canonical_str)

    if sa.segment_type == "system" or sb.segment_type == "system":
        reason = InvalidationReason.SYSTEM_MUTATION
        details = (
            f"System prompt was mutated at segment [{sb.name}]. "
            f"Invalidated downstream {lost_tokens} tokens ({round(lost_tokens/max(1, tokens_a)*100, 1)}% of prior context)."
        )
    elif sa.segment_type == "tool" or sb.segment_type == "tool":
        # Check if it was an added/removed tool or schema key reorder
        if sa.name != sb.name:
            reason = InvalidationReason.TOOL_SET_ALTERATION
            details = (
                f"Tool set altered at index {diverged_idx}: expected '{sa.name}', got '{sb.name}'. "
                f"Dynamic tool loading mid-session destroyed the cache prefix."
            )
        else:
            reason = InvalidationReason.TOOL_SCHEMA_KEY_DRIFT
            details = (
                f"Tool definition for '{sa.name}' changed. "
                f"Schema keys or description were altered between turns."
            )
    else:
        # Message turn changed
        if "summary" in sb.canonical_str.lower() and "summary" not in sa.canonical_str.lower():
            reason = InvalidationReason.COMPACTION_COLLAPSE
            details = f"History at turn [{sb.name}] replaced with compacted summary."
        else:
            details = f"Historical message [{sb.name}] was modified in-place."

    return DivergenceReport(
        reason=reason,
        diverged_segment_index=diverged_idx,
        segment_name=diverged_name,
        matched_tokens=matched_tokens,
        lost_tokens=lost_tokens,
        total_tokens_prev=tokens_a,
        total_tokens_curr=tokens_b,
        details=details,
        diff_snippet=diff_text
    )
