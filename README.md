# agent-cache-lens 🔍

[![CI](https://github.com/Prognosticate-X/agent-cache-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/Prognosticate-X/agent-cache-lens/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-0-success.svg)](pyproject.toml)

> **Zero-dependency Prompt Cache wire sniffer, forensic prefix divergence inspector, and cache preservation guard for AI Agents.**  
> Built to demystify and resolve the real-world **CacheX collapses** (e.g., [anomalyco/opencode#61282](https://github.com/anomalyco/opencode/issues/61282)), mid-turn skill invalidations ([amd/gaia#5021](https://github.com/amd/gaia/issues/5021)), and dynamic schema drift.

[English (US)](README.md) | [中文说明 (Chinese)](README_zh.md)

---

## ⚡ The Problem: Why Agent Prompt Caches Collapse

Modern frontier LLMs (Anthropic Claude 3.5/Opus 5.5, OpenAI GPT-4o, DeepSeek V3) provide **Prompt Caching**, which cuts input token costs by up to **90%** and slashes Time-to-First-Token (TTFT) by up to **85%**.

However, LLM caching engines calculate hashes over the **exact, byte-for-byte serialized token prefix** prior to an ephemeral breakpoint. In real-world multi-turn Agent loops (OpenCode, Claude Code, custom frameworks), developers frequently witness **disastrous cache efficiency drops**:

```
                       [ Prompt Cache Invalidation Triggers ]
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  SYSTEM_MUTATION             TOOL_SET_ALTERATION               SCHEMA_KEY_DRIFT
 Dynamic timestamps,          Dynamic skill load               Non-canonical dict
 git branches, or flags       mid-turn ([amd/gaia#5021])       serialization order
 in system instructions.      shifts tool order.               alters hash prefix.
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                 [ Wire Hash Diverges at Byte Offset 0 ]
                                         ▼
               🔴 0% Cache Hit Rate | 10x Cost | 50s+ Latency Spike
```

### Community Upstream Case Study: [OpenCode #61282](https://github.com/anomalyco/opencode/issues/61282)
* **Observed**: Opus 5.5 through OpenCode demonstrated **CacheX of 16.2x** ($0.78 / MTok), while Native Claude Code achieved **63.3x** ($0.39 / MTok) on identical workloads.
* **Root Cause**:
  1. Compaction triggers early at 170k tokens due to context catalog misattribution ([#61020](https://github.com/anomalyco/opencode/issues/61020)).
  2. Plugin context hooks append dynamic state into the system instruction prefix ([#61248](https://github.com/anomalyco/opencode/issues/61248)).
  3. Tool parameter dictionaries lack deterministic key sorting.

---

## 🛠️ What `agent-cache-lens` Does

`agent-cache-lens` gives developers and framework authors **microsecond-level diagnostic visibility** into prompt cache prefixes with **zero external dependencies**:

1. **Transparent Reverse Proxy & Sniffer (`proxy`)**: Runs locally between your Agent client and upstream API (`api.anthropic.com`), diffing request payloads turn-by-turn to highlight the exact character where cache invalidation occurred.
2. **Offline Session Auditor (`analyze`)**: Ingests session exports (OpenCode, Claude Code traces, HAR logs) and outputs a detailed Markdown audit report detailing token leakage and wasted spend.
3. **A/B Benchmark Comparator (`compare`)**: Evaluates two agent session traces side-by-side to objectively quantify the CacheX gap and token economics.
4. **Active Normalizer Guard (`guard` / `--guard`)**: Intercepts payloads on the fly, enforces recursive schema sorting, isolates dynamic context, and positions optimal ephemeral breakpoints (System, Tools, Turn N-2).

---

## 🚀 Quick Start

### 1. Zero-Install Execution
Because `agent-cache-lens` relies strictly on the Python Standard Library, no `pip install` is required:

```bash
git clone https://github.com/Prognosticate-X/agent-cache-lens.git
cd agent-cache-lens
./bin/agent-cache-lens --help
```

### 2. Run the Live Wire Sniffer
Point your agent client's base URL to `http://localhost:8080`:

```bash
# Start proxy listening on port 8080 forwarding to Anthropic
./bin/agent-cache-lens proxy --port 8080 --upstream https://api.anthropic.com

# Or enable active normalization to automatically protect tool schemas:
./bin/agent-cache-lens proxy --port 8080 --guard
```

**Real-time Terminal Output:**
```text
[Turn 01] Cache Retention: 100.0% (8,500 tokens) | Prefix Intact
[Turn 02] ⚠️ CACHE INVALIDATED! Retention: 0.0% | Reason: SYSTEM_MUTATION
         ↳ Lost 8,500 tokens | System prompt was mutated at segment [system_text].
           Char mismatch at offset 42:
             Prev: ...system engineer...
             Curr: ...system engineer. Current timestamp: 2026-11-03T13:40:15Z...
         ⚡ Metrics: CacheX: 1.82x | Hit Rate: 64.5% | Read: 8,500 | Write: 420 | Session Cost: $0.0611
```

### 3. Compare Two Agent Sessions Side-by-Side (A/B Benchmark)
Quantify the difference between native Claude Code and OpenCode / custom framework:

```bash
./bin/agent-cache-lens compare examples/sample_claude_code_session.json examples/sample_opencode_session.json
```

**Output Benchmark Table:**

| Metric | Native Claude Code | OpenCode (Claude Agent) | Delta |
| :--- | :---: | :---: | :---: |
| **Total Turns** | `3` | `3` | - |
| **CacheX (cache_read / write+input)** | `**1.82x**` | `**0.0x**` | **significantly higher** |
| **Cache Hit Rate** | `64.48%` | `0.0%` | `+64.5%` |
| **Cache Read Tokens** | `17,420` | `0` | - |
| **Cache Write Tokens** | `9,300` | `26,820` | - |
| **Actual Cost** | `**$0.0611**` | `**$0.1745**` | `+$0.1134` |
| **Wasted Cost (Prefix Misses)** | `$0.0008` | `$0.0484` | - |

---

## 📐 Remediation Guidelines for Agent Authors

To guarantee **>90% prompt cache hit rates** across multi-turn agent loops:

1. **Lock the Base System Prefix**: Never inject volatile context (e.g. `datetime.now()`, PID, session UUID, or dynamic agent state) into the static system instructions. Segregate dynamic state into a distinct message block *after* the cached prefix breakpoint.
2. **Alphabetize & Canonicalize Tools**: Always sort tool declarations by tool name and recursively sort parameter JSON schemas before sending to the model provider.
3. **Deferred Skill Attachment**: Do not append newly loaded tools into the middle of active tool lists. Append them strictly at the end or maintain a static global registry.
4. **Anchor Ephemeral Breakpoints**:
   - Breakpoint 1: Static System Instructions.
   - Breakpoint 2: Final Tool Definition in `tools[]`.
   - Breakpoint 3: Second-to-last user turn (`messages[-2]`).

---

## 🧪 Testing

Run the full zero-dependency test suite:

```bash
python3 -m unittest discover -s tests -v
```

---

## 📄 License

MIT © 2026 Prognosticate X
