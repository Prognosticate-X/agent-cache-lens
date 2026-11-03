"""
Offline forensic analyzer for OpenCode exports, Claude Code traces, and raw request dumps.
Generates comprehensive Markdown audit reports and side-by-side A/B comparison tables.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from ..core.diff import analyze_divergence, InvalidationReason, DivergenceReport
from ..core.metrics import CacheSessionMetrics


def load_session_turns(filepath: str) -> List[Dict[str, Any]]:
    """Loads session data from file (supports OpenCode export, raw requests array, or HAR)."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # If it's an OpenCode export
    if isinstance(data, dict):
        if "messages" in data and isinstance(data["messages"], list):
            # Form simulated API request turns
            turns = []
            running_history = []
            system_prompt = data.get("system", "")
            tools = data.get("tools", [])

            for msg in data["messages"]:
                running_history.append(msg)
                if msg.get("role") == "user":
                    turns.append({
                        "system": system_prompt,
                        "tools": tools,
                        "messages": list(running_history),
                        "usage": msg.get("usage", {})
                    })
            return turns
        elif "turns" in data:
            return data["turns"]

    # If it's a raw list of payloads
    if isinstance(data, list):
        return data

    raise ValueError(f"Unrecognized session file format in {filepath}")


class SessionAuditResult:
    """Holds complete audit results for a multi-turn agent session."""
    def __init__(self, name: str, metrics: CacheSessionMetrics, divergences: List[DivergenceReport]):
        self.name = name
        self.metrics = metrics
        self.divergences = divergences

    def generate_markdown_report(self) -> str:
        """Generates a structured GitHub Flavored Markdown report."""
        lines = [
            f"# Prompt Cache Forensic Audit: {self.name}",
            "",
            "## 1. Executive Summary & Economics",
            "",
            "| Metric | Value |",
            "| :--- | :--- |",
            f"| **Model Family** | `{self.metrics.pricing['name']}` |",
            f"| **Total Turns** | `{self.metrics.total_turns}` |",
            f"| **CacheX Multiplier** | `**{self.metrics.cachex}x**` |",
            f"| **Cache Hit Rate** | `**{self.metrics.cache_hit_rate}%**` |",
            f"| **Uncached Input Tokens** | `{self.metrics.uncached_input_tokens:,}` |",
            f"| **Cache Write Tokens** | `{self.metrics.cache_write_tokens:,}` |",
            f"| **Cache Read Tokens** | `{self.metrics.cache_read_tokens:,}` |",
            f"| **Actual Session Cost** | `**${self.metrics.calculate_actual_cost():.4f}**` |",
            f"| **Ideal (Zero Invalidation) Cost** | `${self.metrics.calculate_optimal_cost():.4f}` |",
            f"| **Wasted Expenditure** | `**${self.metrics.cost_waste_from_invalidation:.4f}**` |",
            f"| **TTFT Latency Saved** | `~{self.metrics.estimate_ttft_saved_seconds()}s` |",
            "",
            "## 2. Turn-by-Turn Prefix Divergence Log",
            "",
            "| Turn | Retention | Status | Root Cause | Impact |",
            "| :---: | :---: | :---: | :--- | :--- |"
        ]

        for idx, div in enumerate(self.divergences):
            turn_no = idx + 2
            retention = f"{round(div.cache_retention_ratio * 100, 1)}%"
            status = "🟢 Match" if div.reason == InvalidationReason.NEW_TURN_GROWTH else f"🔴 {div.reason.value}"
            impact = f"-{div.lost_tokens:,} toks" if div.lost_tokens > 0 else "0 toks lost"
            lines.append(f"| {turn_no} | {retention} | {status} | {div.details} | {impact} |")

        lines.extend([
            "",
            "## 3. Recommended Remediation",
            "",
            "- **Tool Ordering**: Enforce recursive dictionary key sorting and alphabetical tool array ordering.",
            "- **Breakpoint Positioning**: Pin ephemeral breakpoints on static system prompts and Turn N-2.",
            "- **Context Segregation**: Separate dynamic session metadata (timestamps, working dir) into separate non-cached blocks.",
            ""
        ])

        return "\n".join(lines)


def audit_session(filepath: str, name: Optional[str] = None, model_family: str = "claude-sonnet") -> SessionAuditResult:
    """Run full forensic cache audit on a session file."""
    turns = load_session_turns(filepath)
    session_name = name or filepath.split("/")[-1]

    metrics = CacheSessionMetrics(model_family=model_family)
    divergences: List[DivergenceReport] = []

    for i in range(len(turns)):
        turn = turns[i]
        usage = turn.get("usage", {})
        metrics.add_turn(
            input_tokens=usage.get("input_tokens", usage.get("uncached_input_tokens", 0)),
            cache_write_tokens=usage.get("cache_creation_input_tokens", usage.get("cache_write_tokens", 0)),
            cache_read_tokens=usage.get("cache_read_input_tokens", usage.get("cache_read_tokens", 0)),
            output_tokens=usage.get("output_tokens", 0)
        )

        if i > 0:
            div = analyze_divergence(turns[i - 1], turns[i])
            divergences.append(div)

    return SessionAuditResult(session_name, metrics, divergences)


def compare_two_sessions(file_a: str, file_b: str, label_a: str = "Native Claude Code", label_b: str = "OpenCode (Claude Agent)") -> str:
    """
    Directly addresses issues like opencode #61282:
    Generates a side-by-side A/B cache efficiency benchmark table.
    """
    res_a = audit_session(file_a, name=label_a)
    res_b = audit_session(file_b, name=label_b)

    if res_b.metrics.cachex > 0:
        ratio_str = f"**{round(res_a.metrics.cachex / res_b.metrics.cachex, 2)}x higher**"
    else:
        ratio_str = "**significantly higher** (target had 0% cache hit rate)"

    cost_diff = round(res_b.metrics.calculate_actual_cost() - res_a.metrics.calculate_actual_cost(), 4)

    lines = [
        f"# A/B Benchmark: {label_a} vs. {label_b}",
        "",
        "### Relative Performance Summary",
        f"- **CacheX Gap**: `{label_a}` achieved {ratio_str} cache reuse than `{label_b}` ({res_a.metrics.cachex}x vs {res_b.metrics.cachex}x).",
        f"- **Cost Difference**: `{label_b}` incurred an additional **${cost_diff:.4f}** over the same workload.",
        "",
        "| Metric | " + label_a + " | " + label_b + " | Delta |",
        "| :--- | :---: | :---: | :---: |",
        f"| **Total Turns** | `{res_a.metrics.total_turns}` | `{res_b.metrics.total_turns}` | - |",
        f"| **CacheX (cache_read / write+input)** | `**{res_a.metrics.cachex}x**` | `**{res_b.metrics.cachex}x**` | `{ratio}x` gap |",
        f"| **Cache Hit Rate** | `{res_a.metrics.cache_hit_rate}%` | `{res_b.metrics.cache_hit_rate}%` | `{round(res_a.metrics.cache_hit_rate - res_b.metrics.cache_hit_rate, 1)}%` |",
        f"| **Cache Read Tokens** | `{res_a.metrics.cache_read_tokens:,}` | `{res_b.metrics.cache_read_tokens:,}` | - |",
        f"| **Cache Write Tokens** | `{res_a.metrics.cache_write_tokens:,}` | `{res_b.metrics.cache_write_tokens:,}` | - |",
        f"| **Actual Cost** | `**${res_a.metrics.calculate_actual_cost():.4f}**` | `**${res_b.metrics.calculate_actual_cost():.4f}**` | `+${cost_diff:.4f}` |",
        f"| **Wasted Cost (Prefix Misses)** | `${res_a.metrics.cost_waste_from_invalidation:.4f}` | `${res_b.metrics.cost_waste_from_invalidation:.4f}` | - |",
        f"| **Latency Saved (TTFT)** | `~{res_a.metrics.estimate_ttft_saved_seconds()}s` | `~{res_b.metrics.estimate_ttft_saved_seconds()}s` | - |",
        "",
        "### Primary Divergence Factors in " + label_b + ":",
        ""
    ]

    invalidations = [d for d in res_b.divergences if d.reason != InvalidationReason.NEW_TURN_GROWTH]
    if not invalidations:
        lines.append("- No early prefix invalidations detected.")
    else:
        for inv in invalidations:
            lines.append(f"- **Turn {inv.diverged_segment_index}**: `{inv.reason.value}` — {inv.details}")

    return "\n".join(lines)
