"""
Zero-dependency transparent reverse proxy and live Prompt Cache profiler.
Intercepts LLM requests, computes prefix divergence in real time, and tallies CacheX.
"""

import http.server
import json
import ssl
import sys
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional

from ..core.diff import analyze_divergence, InvalidationReason
from ..core.metrics import CacheSessionMetrics
from ..core.normalizer import protect_payload


class CacheLensSession:
    """Stateful session tracking turns and prompt cache statistics."""
    def __init__(self, session_id: str, model_family: str = "claude-sonnet"):
        self.session_id = session_id
        self.metrics = CacheSessionMetrics(model_family=model_family)
        self.last_payload: Optional[Dict[str, Any]] = None
        self.history_divergences = []


class CacheLensProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Request Handler that inspects and forwards requests to upstream API."""

    upstream_url: str = "https://api.anthropic.com"
    enable_guard: bool = False
    sessions: Dict[str, CacheLensSession] = {}

    def log_message(self, format, *args):
        # Suppress default noisy access logs to keep terminal output clean
        pass

    def _extract_session_id(self, payload: Dict[str, Any]) -> str:
        """Infer or extract session identifier from payload or headers."""
        # 1. Custom header
        header_sess = self.headers.get("x-session-id") or self.headers.get("x-opencode-session")
        if header_sess:
            return header_sess
        # 2. Anthropic metadata
        meta = payload.get("metadata")
        if isinstance(meta, dict) and "user_id" in meta:
            return str(meta["user_id"])
        # 3. Fallback to client address
        return f"{self.client_address[0]}"

    def do_GET(self):
        """Serve internal diagnostic metrics."""
        if self.path == "/lens/report" or self.path == "/lens/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            data = {
                "active_sessions": len(self.sessions),
                "sessions": {
                    sid: {
                        "metrics": sess.metrics.to_dict(),
                        "divergences": [d.to_dict() for d in sess.history_divergences]
                    }
                    for sid, sess in self.sessions.items()
                }
            }
            self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        """Intercept, analyze, optionally guard, and forward POST requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode('utf-8'))
        except Exception:
            payload = None

        if payload is not None and isinstance(payload, dict):
            session_id = self._extract_session_id(payload)
            if session_id not in self.sessions:
                model = str(payload.get("model", "claude-sonnet")).lower()
                family = "claude-opus" if "opus" in model else ("gpt-4o" if "gpt" in model else "claude-sonnet")
                self.sessions[session_id] = CacheLensSession(session_id, model_family=family)

            sess = self.sessions[session_id]

            # 1. Forensic Divergence Analysis against previous turn
            if sess.last_payload is not None:
                report = analyze_divergence(sess.last_payload, payload)
                sess.history_divergences.append(report)

                retention_pct = round(report.cache_retention_ratio * 100, 1)
                turn_num = sess.metrics.total_turns + 1

                if report.reason == InvalidationReason.NEW_TURN_GROWTH:
                    print(f"\033[32m[Turn {turn_num:02d}]\033[0m Cache Retention: \033[1;32m{retention_pct}%\033[0m ({report.matched_tokens:,} tokens) | \033[32mPrefix Intact\033[0m", file=sys.stderr)
                else:
                    print(f"\033[31m[Turn {turn_num:02d}] ⚠️ CACHE INVALIDATED!\033[0m Retention: \033[1;31m{retention_pct}%\033[0m | Reason: \033[1;33m{report.reason.value}\033[0m", file=sys.stderr)
                    print(f"         \033[90m↳ Lost {report.lost_tokens:,} tokens | {report.details}\033[0m", file=sys.stderr)
                    if report.diff_snippet:
                        for line in report.diff_snippet.splitlines()[:3]:
                            print(f"           \033[36m{line}\033[0m", file=sys.stderr)

            # 2. Optional Normalizer Guard
            if self.enable_guard:
                payload = protect_payload(payload)
                raw_body = json.dumps(payload).encode('utf-8')

            # Update last payload for next turn
            sess.last_payload = payload

        # 3. Forward to Upstream
        target_url = self.upstream_url.rstrip("/") + self.path
        req = urllib.request.Request(target_url, data=raw_body, method="POST")

        for key, value in self.headers.items():
            if key.lower() not in ["host", "content-length"]:
                req.add_header(key, value)
        req.add_header("Host", urllib.parse.urlparse(self.upstream_url).netloc)

        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx) as resp:
                resp_status = resp.status
                resp_headers = resp.headers
                resp_body = resp.read()
        except urllib.error.HTTPError as e:
            resp_status = e.code
            resp_headers = e.headers
            resp_body = e.read()
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Proxy upstream connection error: {str(e)}".encode('utf-8'))
            return

        # 4. Parse Usage from Upstream Response
        if payload is not None and resp_status == 200:
            try:
                resp_json = json.loads(resp_body.decode('utf-8'))
                usage = resp_json.get("usage", {})
                uncached = usage.get("input_tokens", 0)
                write = usage.get("cache_creation_input_tokens", 0)
                read = usage.get("cache_read_input_tokens", 0)
                output = usage.get("output_tokens", 0)

                sess.metrics.add_turn(
                    input_tokens=uncached,
                    cache_write_tokens=write,
                    cache_read_tokens=read,
                    output_tokens=output
                )

                print(
                    f"         \033[1;34m⚡ Metrics:\033[0m CacheX: \033[1;35m{sess.metrics.cachex}x\033[0m | "
                    f"Hit Rate: \033[1;36m{sess.metrics.cache_hit_rate}%\033[0m | "
                    f"Read: {read:,} | Write: {write:,} | Session Cost: ${sess.metrics.calculate_actual_cost():.4f}",
                    file=sys.stderr
                )
            except Exception:
                pass

        # 5. Return Response to Client
        self.send_response(resp_status)
        for key, value in resp_headers.items():
            if key.lower() not in ["transfer-encoding", "content-length"]:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)


def run_proxy(
    port: int = 8080,
    upstream_url: str = "https://api.anthropic.com",
    enable_guard: bool = False
) -> None:
    """Start the Cache Lens proxy server."""
    CacheLensProxyHandler.upstream_url = upstream_url
    CacheLensProxyHandler.enable_guard = enable_guard

    server_address = ("", port)
    httpd = http.server.HTTPServer(server_address, CacheLensProxyHandler)
    guard_status = "\033[1;32mActive (Auto-stabilizing schemas & breakpoints)\033[0m" if enable_guard else "\033[90mPassive (Sniffer only)\033[0m"
    print(f"\n\033[1;36m=====================================================\033[0m", file=sys.stderr)
    print(f"\033[1;32m  agent-cache-lens: Prompt Cache Sniffer & Guard\033[0m", file=sys.stderr)
    print(f"\033[1;36m=====================================================\033[0m", file=sys.stderr)
    print(f"  • Listening on:    \033[1;33mhttp://localhost:{port}\033[0m", file=sys.stderr)
    print(f"  • Upstream:        \033[1;34m{upstream_url}\033[0m", file=sys.stderr)
    print(f"  • Normalizer Guard: {guard_status}", file=sys.stderr)
    print(f"  • Metrics endpoint: \033[36mhttp://localhost:{port}/lens/report\033[0m\n", file=sys.stderr)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[agent-cache-lens] Proxy stopped.", file=sys.stderr)
