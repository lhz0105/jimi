"""价格表与成本估算（每 1K tokens，币种随用户网关计费）。"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class PriceTable:
    main_input_per_1k: float
    main_output_per_1k: float
    vision_input_per_1k: float
    vision_output_per_1k: float
    main_input_cache_hit_per_1k: float = 0.0


def load_prices(settings: Settings) -> PriceTable:
    return PriceTable(
        main_input_per_1k=settings.pricing_main_input_per_1k,
        main_output_per_1k=settings.pricing_main_output_per_1k,
        vision_input_per_1k=settings.pricing_vision_input_per_1k,
        vision_output_per_1k=settings.pricing_vision_output_per_1k,
        main_input_cache_hit_per_1k=settings.pricing_main_input_cache_hit_per_1k,
    )


def estimate_cost(
    usage: dict, prices: PriceTable, *, role: str = "main"
) -> float:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    if role == "vision":
        return (
            prompt / 1000 * prices.vision_input_per_1k
            + completion / 1000 * prices.vision_output_per_1k
        )
    cache_read = min(int(usage.get("cache_read_tokens") or 0), prompt)
    uncached = max(0, prompt - cache_read)
    return (
        uncached / 1000 * prices.main_input_per_1k
        + cache_read / 1000 * prices.main_input_cache_hit_per_1k
        + completion / 1000 * prices.main_output_per_1k
    )
