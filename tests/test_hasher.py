import unittest
from agent_cache_lens.core.hasher import (
    canonical_serialize,
    compute_sha256,
    estimate_token_count,
    extract_segments
)


class TestHasher(unittest.TestCase):
    def test_canonical_serialize_key_ordering(self):
        # Two dictionaries with different key insertion orders
        dict_a = {"b": 2, "a": 1, "nested": {"z": 26, "y": 25}}
        dict_b = {"nested": {"y": 25, "z": 26}, "a": 1, "b": 2}

        str_a = canonical_serialize(dict_a)
        str_b = canonical_serialize(dict_b)

        self.assertEqual(str_a, str_b)
        self.assertEqual(compute_sha256(str_a), compute_sha256(str_b))

    def test_estimate_token_count(self):
        eng = "This is a standard English test prompt for caching."
        cjk = "这是一个用于测试提示词缓存的前缀。"
        self.assertGreater(estimate_token_count(eng), 5)
        self.assertGreater(estimate_token_count(cjk), 5)

    def test_extract_segments(self):
        payload = {
            "system": "System instructions",
            "tools": [{"name": "read_file", "description": "Reads file"}],
            "messages": [{"role": "user", "content": "Hello"}]
        }
        segs = extract_segments(payload)
        self.assertEqual(len(segs), 3)
        self.assertEqual(segs[0].segment_type, "system")
        self.assertEqual(segs[1].segment_type, "tool")
        self.assertEqual(segs[2].segment_type, "message")


if __name__ == "__main__":
    unittest.main()
