"""DeepSeek Flash 谷值计费：缓存命中与未命中输入分别计价。"""

from __future__ import annotations

from app.llm.pricing import PriceTable, estimate_cost


def test_deepseek_flash_offpeak_cost_with_cache_hit() -> None:
    prices = PriceTable(
        main_input_per_1k=0.001,
        main_output_per_1k=0.004,
        vision_input_per_1k=0.002,
        vision_output_per_1k=0.004,
        main_input_cache_hit_per_1k=0.00002,
    )
    usage = {"prompt_tokens": 1000, "completion_tokens": 1000, "cache_read_tokens": 400}
    expected = (
        600 / 1000 * 0.001
        + 400 / 1000 * 0.00002
        + 1000 / 1000 * 0.004
    )
    assert abs(estimate_cost(usage, prices) - expected) < 1e-12
