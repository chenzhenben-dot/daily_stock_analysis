# -*- coding: utf-8 -*-
"""Tests pinning the per-region turnover unit in _build_indices_block.

需求：即使 breadth 缺失（无涨跌家数 / 成交额数据），指数行情表的"成交额(...)"
表头也必须按市场固定为：
- cn: 成交额(亿)
- hk: 成交额(十亿港元)
- us: 成交额(亿美元)
- jp: 成交额(十亿日元)
- kr: 成交额(十亿韩元)

数字缺失必须显示 N/A，绝不生成假数据。

US 原始 USD 成交额 179_599_561_831 必须显示 "1796.00 亿美元"。
页面不出现 "179599561831 亿"。

CN 测试仍保持"成交额(亿)"。
"""

import re
import sys
import unittest
from unittest.mock import MagicMock

for _mod in ("newspaper", "litellm", "google.generativeai", "google.genai", "anthropic", "fake_useragent"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview


def _make_analyzer(region: str, language: str = "zh") -> MarketAnalyzer:
    analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
    analyzer.region = region
    analyzer.profile = None
    analyzer.config = MagicMock()
    analyzer._get_review_language = MagicMock(return_value=language)
    analyzer._get_output_language = MagicMock(return_value=language)
    analyzer._get_turnover_unit_label = (
        lambda r=region, l=language: MarketAnalyzer(region=r)._get_turnover_unit_label()
        if False else MarketAnalyzer._static_unit_label(r, l)
    )
    return analyzer


class TestIndicesBlockTurnoverHeader(unittest.TestCase):
    """需求 #1-#5: 指数表头单位在 breadth 缺失时仍按 region 固定."""

    EXPECTED_HEADER = {
        "cn": "成交额(亿)",
        "hk": "成交额(十亿港元)",
        "us": "成交额(亿美元)",
        "jp": "成交额(十亿日元)",
        "kr": "成交额(十亿韩元)",
    }

    def _overview_with_indices_only(self, region: str) -> MarketOverview:
        return MarketOverview(
            date="2026-07-23",
            indices=[
                MarketIndex(code="SPX", name="标普500", current=6200.0, change_pct=0.5)
                if region == "us"
                else MarketIndex(code="000001", name="上证指数", current=3876.0, change_pct=0.25),
            ],
            up_count=0,
            down_count=0,
            flat_count=0,
            total_amount=0.0,
        )

    def test_cn_indices_header_is_yi_when_breadth_missing(self):
        an = MarketAnalyzer(region="cn")
        block = an._build_indices_block(self._overview_with_indices_only("cn"))
        self.assertIn(self.EXPECTED_HEADER["cn"], block)
        self.assertNotIn("亿美", block)
        self.assertNotIn("十亿美元", block)

    def test_hk_indices_header_is_hkd_bn_when_breadth_missing(self):
        an = MarketAnalyzer(region="hk")
        block = an._build_indices_block(self._overview_with_indices_only("hk"))
        self.assertIn(self.EXPECTED_HEADER["hk"], block)

    def test_us_indices_header_is_usd_bn_when_breadth_missing(self):
        an = MarketAnalyzer(region="us")
        block = an._build_indices_block(self._overview_with_indices_only("us"))
        self.assertIn(self.EXPECTED_HEADER["us"], block)
        self.assertNotIn("成交额(亿)", block)

    def test_jp_indices_header_is_jpy_bn_when_breadth_missing(self):
        an = MarketAnalyzer(region="jp")
        block = an._build_indices_block(self._overview_with_indices_only("jp"))
        self.assertIn(self.EXPECTED_HEADER["jp"], block)

    def test_kr_indices_header_is_krw_bn_when_breadth_missing(self):
        an = MarketAnalyzer(region="kr")
        block = an._build_indices_block(self._overview_with_indices_only("kr"))
        self.assertIn(self.EXPECTED_HEADER["kr"], block)


class TestIndicesBlockTurnoverConversion(unittest.TestCase):
    """需求 #6: 179_599_561_831 USD → 1796.00 亿美元; 页面无 179599561831 亿."""

    def test_us_raw_usd_amount_renders_as_usd_bn(self):
        an = MarketAnalyzer(region="us")
        overview = MarketOverview(
            date="2026-07-23",
            indices=[MarketIndex(
                code="SPX", name="标普500", current=6200.0, change_pct=0.5,
                amount=179_599_561_831.0,
            )],
            up_count=0, down_count=0, flat_count=0, total_amount=179_599_561_831.0,
        )
        block = an._build_indices_block(overview)

        self.assertIn("1796.00 亿美元", block)
        self.assertNotIn("179599561831 亿", block)
        self.assertNotIn("179599561831 亿美元", block)
        self.assertNotIn("179.60 十亿美元", block)

    def test_us_english_prompt_usd_bn(self):
        an = MarketAnalyzer(region="us")
        an._get_review_language = MagicMock(return_value="en")
        overview = MarketOverview(
            date="2026-07-23",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=6200.0, change_pct=0.5,
                                amount=179_599_561_831.0)],
            up_count=0, down_count=0, flat_count=0, total_amount=179_599_561_831.0,
        )
        block = an._build_indices_block(overview)
        self.assertIn("USD 100m", block)  # 英文单位
        self.assertIn("1796.00", block)


class TestIndicesBlockRendersWhenBreadthEmpty(unittest.TestCase):
    """需求: breadth 缺失但 indices 存在时，指数表仍然渲染（含正确表头 + N/A cell）。"""

    def test_us_indices_block_renders_without_breadth(self):
        an = MarketAnalyzer(region="us")
        overview = MarketOverview(
            date="2026-07-23",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=6200.0, change_pct=0.5)],
            up_count=0, down_count=0, flat_count=0, total_amount=0.0,
        )
        block = an._build_indices_block(overview)
        self.assertNotEqual(block, "", msg="指数表不应为空")
        self.assertIn("S&P 500", block)
        self.assertIn("成交额(亿美元)", block)


class TestCnYiUnchanged(unittest.TestCase):
    """需求 #8: CN 测试仍保持"成交额(亿)"."""

    def test_cn_indices_block_uses_yi(self):
        an = MarketAnalyzer(region="cn")
        overview = MarketOverview(
            date="2026-07-23",
            indices=[MarketIndex(code="000001", name="上证指数", current=3876.0, change_pct=0.25,
                                amount=387600000000.0)],
            up_count=3120, down_count=1420, total_amount=960000000000.0,
        )
        block = an._build_indices_block(overview)
        self.assertIn("成交额(亿)", block)
        # 387600000000 / 1e8 = 3876 → "3876 亿"（CN 既有无小数行为，不被破坏）
        self.assertIn("3876 亿", block)


if __name__ == "__main__":
    unittest.main()