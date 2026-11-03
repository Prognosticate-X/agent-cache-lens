import unittest
from agent_cache_lens.core.metrics import CacheSessionMetrics


class TestMetrics(unittest.TestCase):
    def test_cachex_calculation(self):
        metrics = CacheSessionMetrics(model_family="claude-sonnet")
        # 1000 input, 1000 write, 8000 read
        # cachex = 8000 / (1000 + 1000) = 4.0
        metrics.add_turn(input_tokens=1000, cache_write_tokens=1000, cache_read_tokens=8000, output_tokens=500)
        self.assertEqual(metrics.cachex, 4.0)
        self.assertEqual(metrics.cache_hit_rate, 80.0)

    def test_cost_calculation(self):
        metrics = CacheSessionMetrics(model_family="claude-sonnet")
        metrics.add_turn(input_tokens=0, cache_write_tokens=1_000_000, cache_read_tokens=1_000_000, output_tokens=0)
        # 1M write ($3.75) + 1M read ($0.30) = $4.05
        cost = metrics.calculate_actual_cost()
        self.assertAlmostEqual(cost, 4.05, places=2)


if __name__ == "__main__":
    unittest.main()
