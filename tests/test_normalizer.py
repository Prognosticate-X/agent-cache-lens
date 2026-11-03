import unittest
from agent_cache_lens.core.normalizer import canonicalize_tools, place_optimal_breakpoints, protect_payload


class TestNormalizer(unittest.TestCase):
    def test_canonicalize_tools_sorting(self):
        unsorted_tools = [
            {"name": "zebra_tool", "parameters": {"properties": {"b": 2, "a": 1}}},
            {"name": "alpha_tool", "parameters": {"properties": {"z": 26, "y": 25}}}
        ]
        sorted_tools = canonicalize_tools(unsorted_tools)
        self.assertEqual(sorted_tools[0]["name"], "alpha_tool")
        self.assertEqual(sorted_tools[1]["name"], "zebra_tool")
        self.assertEqual(list(sorted_tools[0]["parameters"]["properties"].keys()), ["y", "z"])

    def test_place_optimal_breakpoints(self):
        payload = {
            "system": "Base system prompt",
            "tools": [{"name": "read_file", "parameters": {}}],
            "messages": [
                {"role": "user", "content": "Turn 1"},
                {"role": "assistant", "content": "Resp 1"},
                {"role": "user", "content": "Turn 2"}
            ]
        }
        guarded = place_optimal_breakpoints(payload)
        # Check system has cache_control
        self.assertIn("cache_control", guarded["system"][0])
        # Check tool has cache_control
        self.assertIn("cache_control", guarded["tools"][-1])
        # Check Turn N-2 (messages[-2]) has cache_control
        self.assertIn("cache_control", guarded["messages"][-2]["content"][0])


if __name__ == "__main__":
    unittest.main()
