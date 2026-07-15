# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview


class MarketAnalyzerFredTest(unittest.TestCase):
    def _analyzer(self, region: str) -> MarketAnalyzer:
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = region
        analyzer.profile = SimpleNamespace(
            has_market_stats=False,
            has_sector_rankings=region == "us",
            prompt_index_hint="indices",
        )
        analyzer.config = SimpleNamespace(report_language="zh", market_review_color_scheme="green_up")
        analyzer.data_manager = Mock()
        analyzer.search_service = None
        analyzer.analyzer = None
        return analyzer

    def test_us_overview_fetches_fred_macro_snapshot(self) -> None:
        analyzer = self._analyzer("us")
        analyzer._get_main_indices = Mock(return_value=[])
        analyzer._get_sector_rankings = Mock()
        analyzer._fred_macro_adapter = Mock()
        analyzer._fred_macro_adapter.fetch_snapshot.return_value = [
            {"series_id": "DGS10", "name_zh": "美国10年期国债收益率", "value": 4.56}
        ]

        overview = analyzer.get_market_overview()

        self.assertEqual(overview.macro_indicators[0]["series_id"], "DGS10")

    def test_non_us_overview_does_not_fetch_fred(self) -> None:
        analyzer = self._analyzer("hk")
        analyzer._get_main_indices = Mock(return_value=[])
        analyzer._fred_macro_adapter = Mock()

        overview = analyzer.get_market_overview()

        self.assertEqual(overview.macro_indicators, [])
        analyzer._fred_macro_adapter.fetch_snapshot.assert_not_called()

    def test_prompt_and_payload_include_macro_snapshot(self) -> None:
        analyzer = self._analyzer("us")
        analyzer.strategy = SimpleNamespace()
        analyzer._get_strategy_prompt_block = Mock(return_value="")
        overview = MarketOverview(
            date="2026-07-14",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=6300, change_pct=0.4)],
            macro_indicators=[
                {
                    "series_id": "DGS10",
                    "name_zh": "美国10年期国债收益率",
                    "name_en": "10-Year Treasury Yield",
                    "value": 4.56,
                    "previous_value": 4.54,
                    "change": 0.02,
                    "unit": "%",
                    "observation_date": "2026-07-10",
                    "source": "FRED",
                }
            ],
        )

        prompt = analyzer._build_review_prompt(overview, [])
        payload = analyzer.build_market_review_payload(overview, [], "## 复盘")

        self.assertIn("美国10年期国债收益率", prompt)
        self.assertIn("4.56%", prompt)
        self.assertEqual(payload["macro"][0]["series_id"], "DGS10")


if __name__ == "__main__":
    unittest.main()
