"""
Command Line Interface (CLI) for agent-cache-lens.
"""

import argparse
import json
import sys
from typing import Optional

from .proxy.server import run_proxy
from .analyzer.session import audit_session, compare_two_sessions
from .core.normalizer import protect_payload


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-cache-lens",
        description="Zero-dependency Prompt Cache wire sniffer, forensic divergence analyzer, and guard for AI Agents."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Proxy
    proxy_parser = subparsers.add_parser("proxy", help="Run live transparent HTTP reverse proxy and cache sniffer")
    proxy_parser.add_argument("--port", "-p", type=int, default=8080, help="Local listening port (default: 8080)")
    proxy_parser.add_argument("--upstream", "-u", type=str, default="https://api.anthropic.com", help="Upstream API base URL (default: https://api.anthropic.com)")
    proxy_parser.add_argument("--guard", "-g", action="store_true", help="Enable active normalizer guard to stabilize tool schemas and breakpoints")

    # 2. Analyze
    analyze_parser = subparsers.add_parser("analyze", help="Run forensic audit on an offline session JSON dump")
    analyze_parser.add_argument("session_file", type=str, help="Path to session JSON file (OpenCode export, Claude Code trace, or raw array)")
    analyze_parser.add_argument("--model", "-m", type=str, default="claude-sonnet", choices=["claude-sonnet", "claude-opus", "gpt-4o", "deepseek-v3"], help="Model pricing family")
    analyze_parser.add_argument("--out", "-o", type=str, default=None, help="Save markdown report to file")

    # 3. Compare
    compare_parser = subparsers.add_parser("compare", help="Compare two sessions side-by-side (e.g. Native Claude Code vs OpenCode)")
    compare_parser.add_argument("session_a", type=str, help="Baseline session file (e.g. Native Claude Code)")
    compare_parser.add_argument("session_b", type=str, help="Target session file (e.g. OpenCode)")
    compare_parser.add_argument("--label-a", type=str, default="Native Claude Code", help="Label for baseline")
    compare_parser.add_argument("--label-b", type=str, default="OpenCode (Claude Agent)", help="Label for target")
    compare_parser.add_argument("--out", "-o", type=str, default=None, help="Save markdown comparison table to file")

    # 4. Guard
    guard_parser = subparsers.add_parser("guard", help="Normalize a JSON payload to guarantee canonical schemas and optimal breakpoints")
    guard_parser.add_argument("input_file", type=str, help="Input payload JSON file")
    guard_parser.add_argument("--out", "-o", type=str, default=None, help="Output normalized JSON file (prints to stdout if omitted)")

    args = parser.parse_args()

    if args.command == "proxy":
        run_proxy(port=args.port, upstream_url=args.upstream, enable_guard=args.guard)

    elif args.command == "analyze":
        res = audit_session(args.session_file, model_family=args.model)
        report = res.generate_markdown_report()
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"Audit report saved to: {args.out}")
        else:
            print(report)

    elif args.command == "compare":
        report = compare_two_sessions(args.session_a, args.session_b, label_a=args.label_a, label_b=args.label_b)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"Comparison report saved to: {args.out}")
        else:
            print(report)

    elif args.command == "guard":
        with open(args.input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        guarded = protect_payload(data)
        serialized = json.dumps(guarded, indent=2, ensure_ascii=False)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(serialized)
            print(f"Guarded payload saved to: {args.out}")
        else:
            print(serialized)


if __name__ == "__main__":
    main()
