"""
Financial cost models, CacheX multiplier calculation, and latency projection.
Directly models Anthropic, OpenAI, and DeepSeek prompt caching economics.
"""

from typing import Any, Dict, Optional


# Pricing in USD per Million Tokens (MTok)
PROVIDER_PRICING = {
    "claude-opus": {
        "name": "Claude Opus 3.5 / 5.5",
        "base_input_per_m": 15.00,
        "cache_write_per_m": 18.75,
        "cache_read_per_m": 1.50,
        "output_per_m": 75.00,
        "prefill_ms_per_1k": 35.0,
        "cache_read_ms_per_1k": 3.0,
    },
    "claude-sonnet": {
        "name": "Claude Sonnet 3.5 / 3.7",
        "base_input_per_m": 3.00,
        "cache_write_per_m": 3.75,
        "cache_read_per_m": 0.30,
        "output_per_m": 15.00,
        "prefill_ms_per_1k": 18.0,
        "cache_read_ms_per_1k": 2.0,
    },
    "gpt-4o": {
        "name": "OpenAI GPT-4o",
        "base_input_per_m": 2.50,
        "cache_write_per_m": 2.50,
        "cache_read_per_m": 1.25,
        "output_per_m": 10.00,
        "prefill_ms_per_1k": 15.0,
        "cache_read_ms_per_1k": 2.0,
    },
    "deepseek-v3": {
        "name": "DeepSeek V3",
        "base_input_per_m": 0.14,
        "cache_write_per_m": 0.14,
        "cache_read_per_m": 0.014,
        "output_per_m": 0.28,
        "prefill_ms_per_1k": 10.0,
        "cache_read_ms_per_1k": 1.5,
    }
}


class CacheSessionMetrics:
    """Tracks token consumption and cache economics over a multi-turn session."""
    def __init__(self, model_family: str = "claude-sonnet"):
        self.model_family = model_family if model_family in PROVIDER_PRICING else "claude-sonnet"
        self.pricing = PROVIDER_PRICING[self.model_family]

        self.total_turns: int = 0
        self.uncached_input_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.cache_read_tokens: int = 0
        self.output_tokens: int = 0

    def add_turn(
        self,
        input_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        output_tokens: int = 0
    ) -> None:
        """Record usage from a single API response."""
        self.total_turns += 1
        self.uncached_input_tokens += input_tokens
        self.cache_write_tokens += cache_write_tokens
        self.cache_read_tokens += cache_read_tokens
        self.output_tokens += output_tokens

    @property
    def cachex(self) -> float:
        """
        CacheX multiplier as defined by Tokscale / OpenCode:
        CacheX = cache_read / (uncached_input + cache_write)
        """
        denominator = self.uncached_input_tokens + self.cache_write_tokens
        if denominator == 0:
            return float('inf') if self.cache_read_tokens > 0 else 0.0
        return round(self.cache_read_tokens / denominator, 2)

    @property
    def cache_hit_rate(self) -> float:
        """Percentage of total input tokens served from cache."""
        total_input = self.uncached_input_tokens + self.cache_write_tokens + self.cache_read_tokens
        if total_input == 0:
            return 0.0
        return round((self.cache_read_tokens / total_input) * 100.0, 2)

    def calculate_actual_cost(self) -> float:
        """Calculate total actual cost in USD based on provider rates."""
        cost = (
            (self.uncached_input_tokens / 1_000_000) * self.pricing["base_input_per_m"]
            + (self.cache_write_tokens / 1_000_000) * self.pricing["cache_write_per_m"]
            + (self.cache_read_tokens / 1_000_000) * self.pricing["cache_read_per_m"]
            + (self.output_tokens / 1_000_000) * self.pricing["output_per_m"]
        )
        return round(cost, 4)

    def calculate_unoptimized_cost(self) -> float:
        """Calculate what the session would cost if cache hit rate was 0%."""
        total_input = self.uncached_input_tokens + self.cache_write_tokens + self.cache_read_tokens
        cost = (
            (total_input / 1_000_000) * self.pricing["base_input_per_m"]
            + (self.output_tokens / 1_000_000) * self.pricing["output_per_m"]
        )
        return round(cost, 4)

    def calculate_optimal_cost(self) -> float:
        """
        Calculate ideal cost if prefix was never invalidated
        (1 cache write at turn 1, all rest cache reads).
        """
        total_input = self.uncached_input_tokens + self.cache_write_tokens + self.cache_read_tokens
        first_turn_write = min(total_input, self.cache_write_tokens if self.cache_write_tokens > 0 else 10000)
        subsequent_reads = max(0, total_input - first_turn_write)
        cost = (
            (first_turn_write / 1_000_000) * self.pricing["cache_write_per_m"]
            + (subsequent_reads / 1_000_000) * self.pricing["cache_read_per_m"]
            + (self.output_tokens / 1_000_000) * self.pricing["output_per_m"]
        )
        return round(cost, 4)

    @property
    def cost_waste_from_invalidation(self) -> float:
        """Dollar amount wasted due to prefix cache misses and re-writes."""
        actual = self.calculate_actual_cost()
        optimal = self.calculate_optimal_cost()
        return round(max(0.0, actual - optimal), 4)

    def estimate_ttft_saved_seconds(self) -> float:
        """Estimated seconds saved across all turns due to cache reads."""
        tokens_k = self.cache_read_tokens / 1000.0
        time_saved_ms = tokens_k * (self.pricing["prefill_ms_per_1k"] - self.pricing["cache_read_ms_per_1k"])
        return round(max(0.0, time_saved_ms / 1000.0), 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_family": self.pricing["name"],
            "total_turns": self.total_turns,
            "cachex": self.cachex,
            "cache_hit_rate_percent": self.cache_hit_rate,
            "uncached_input_tokens": self.uncached_input_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "output_tokens": self.output_tokens,
            "actual_cost_usd": self.calculate_actual_cost(),
            "unoptimized_cost_usd": self.calculate_unoptimized_cost(),
            "optimal_cost_usd": self.calculate_optimal_cost(),
            "wasted_cost_usd": self.cost_waste_from_invalidation,
            "ttft_seconds_saved": self.estimate_ttft_saved_seconds()
        }
