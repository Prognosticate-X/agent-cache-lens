import unittest
import os
from agent_cache_lens.analyzer.session import audit_session, compare_two_sessions


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.sample_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "examples"))
        self.claude_session = os.path.join(self.sample_dir, "sample_claude_code_session.json")
        self.opencode_session = os.path.join(self.sample_dir, "sample_opencode_session.json")

    def test_audit_claude_code_session(self):
        res = audit_session(self.claude_session, name="Claude Code")
        self.assertGreater(res.metrics.cachex, 1.5)
        report = res.generate_markdown_report()
        self.assertIn("Prompt Cache Forensic Audit", report)

    def test_compare_two_sessions(self):
        report = compare_two_sessions(self.claude_session, self.opencode_session)
        self.assertIn("A/B Benchmark", report)
        self.assertIn("CacheX Gap", report)


if __name__ == "__main__":
    unittest.main()
