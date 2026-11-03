import unittest
from agent_cache_lens.core.diff import analyze_divergence, InvalidationReason


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.base_payload = {
            "system": "You are a coding assistant.",
            "tools": [{"name": "read_file", "parameters": {"type": "object"}}],
            "messages": [{"role": "user", "content": "Turn 1"}]
        }

    def test_clean_turn_growth(self):
        turn_2 = {
            "system": "You are a coding assistant.",
            "tools": [{"name": "read_file", "parameters": {"type": "object"}}],
            "messages": [
                {"role": "user", "content": "Turn 1"},
                {"role": "assistant", "content": "Response 1"},
                {"role": "user", "content": "Turn 2"}
            ]
        }
        report = analyze_divergence(self.base_payload, turn_2)
        self.assertEqual(report.reason, InvalidationReason.NEW_TURN_GROWTH)
        self.assertEqual(report.lost_tokens, 0)
        self.assertEqual(report.cache_retention_ratio, 1.0)

    def test_system_prompt_mutation(self):
        mutated_turn = {
            "system": "You are a coding assistant. Current time: 2026-11-03T13:40:00Z",
            "tools": [{"name": "read_file", "parameters": {"type": "object"}}],
            "messages": [{"role": "user", "content": "Turn 1"}]
        }
        report = analyze_divergence(self.base_payload, mutated_turn)
        self.assertEqual(report.reason, InvalidationReason.SYSTEM_MUTATION)
        self.assertEqual(report.matched_tokens, 0)
        self.assertGreater(report.lost_tokens, 0)

    def test_tool_set_alteration(self):
        mutated_turn = {
            "system": "You are a coding assistant.",
            "tools": [
                {"name": "dynamic_skill_tool", "parameters": {"type": "object"}},
                {"name": "read_file", "parameters": {"type": "object"}}
            ],
            "messages": [{"role": "user", "content": "Turn 1"}]
        }
        report = analyze_divergence(self.base_payload, mutated_turn)
        self.assertEqual(report.reason, InvalidationReason.TOOL_SET_ALTERATION)


if __name__ == "__main__":
    unittest.main()
