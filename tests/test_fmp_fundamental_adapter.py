from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "fake_useragent" not in sys.modules:
    sys.modules["fake_useragent"] = MagicMock()

from data_provider.base import DataFetcherManager
from data_provider.fmp_fundamental_adapter import FmpFundamentalAdapter
from src.analyzer import GeminiAnalyzer


class TestFmpFundamentalAdapter(unittest.TestCase):
    def setUp(self) -> None:
        FmpFundamentalAdapter._cache.clear()

    def _request_json(self, path: str, params: dict):
        self.assertEqual(params["symbol"], "AAPL")
        if path == "profile":
            return [{
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "exchangeShortName": "NASDAQ",
                "country": "US",
            }]
        if path == "ratios-ttm":
            return [{
                "priceEarningsRatioTTM": 31.2,
                "priceToBookRatioTTM": 42.1,
                "priceToSalesRatioTTM": 8.2,
                "enterpriseValueMultipleTTM": 24.4,
                "freeCashFlowYieldTTM": 3.1,
                "returnOnEquityTTM": 1.52,
                "grossProfitMarginTTM": 0.469,
                "netProfitMarginTTM": 0.269,
                "currentRatioTTM": 0.89,
                "quickRatioTTM": 0.76,
                "debtEquityRatioTTM": 1.87,
                "interestCoverageTTM": 33.2,
            }]
        if path == "key-metrics-ttm":
            return [{
                "marketCap": 3100000000000,
                "enterpriseValueTTM": 3150000000000,
                "evToSalesTTM": 8.4,
                "evToEBITDATTM": 24.2,
                "netDebtToEBITDATTM": 0.55,
                "roicTTM": 0.61,
            }]
        raise AssertionError(path)

    def test_builds_ttm_valuation_quality_and_profile(self) -> None:
        adapter = FmpFundamentalAdapter(api_key="secret", request_json=self._request_json)

        bundle = adapter.get_fundamental_bundle("AAPL")

        self.assertEqual(bundle["status"], "partial")
        self.assertEqual(bundle["provider"], "fmp")
        valuation = bundle["earnings"]["valuation_metrics"]
        self.assertEqual(valuation["pe_ratio_ttm"], 31.2)
        self.assertEqual(valuation["ev_to_ebitda_ttm"], 24.2)
        self.assertEqual(valuation["free_cash_flow_yield_ttm_pct"], 3.1)
        quality = bundle["earnings"]["quality_metrics"]
        self.assertEqual(quality["roic_ttm_pct"], 61.0)
        self.assertEqual(quality["gross_margin_ttm_pct"], 46.9)
        health = bundle["earnings"]["financial_health"]
        self.assertEqual(health["debt_to_equity_ttm"], 1.87)
        self.assertEqual(bundle["company_profile"]["company_name"], "Apple Inc.")
        self.assertEqual(len(bundle["belong_boards"]), 2)

    def test_missing_key_skips_requests_without_error(self) -> None:
        request_json = MagicMock()
        with patch.dict(os.environ, {}, clear=True):
            adapter = FmpFundamentalAdapter(api_key="", request_json=request_json)
            bundle = adapter.get_fundamental_bundle("AAPL")

        self.assertEqual(bundle["status"], "not_configured")
        self.assertEqual(bundle["errors"], [])
        request_json.assert_not_called()

    def test_non_us_symbol_is_not_supported(self) -> None:
        adapter = FmpFundamentalAdapter(api_key="secret", request_json=self._request_json)
        self.assertEqual(adapter.get_fundamental_bundle("0700.HK")["status"], "not_supported")

    def test_request_failure_is_fail_open(self) -> None:
        def fail(_path: str, _params: dict):
            raise TimeoutError("FMP timeout")

        bundle = FmpFundamentalAdapter(api_key="secret", request_json=fail).get_fundamental_bundle("AAPL")
        self.assertEqual(bundle["status"], "not_supported")
        self.assertTrue(bundle["errors"])

    def test_successful_bundle_is_cached(self) -> None:
        calls = 0

        def request_json(path: str, params: dict):
            nonlocal calls
            calls += 1
            return self._request_json(path, params)

        adapter = FmpFundamentalAdapter(
            api_key="secret",
            request_json=request_json,
            cache_ttl_seconds=3600,
        )

        first = adapter.get_fundamental_bundle("AAPL")
        second = adapter.get_fundamental_bundle("AAPL")

        self.assertEqual(first, second)
        self.assertEqual(calls, 3)


class TestFmpBundleMerge(unittest.TestCase):
    def test_fmp_supplements_sec_and_yfinance_without_overriding_sec_report(self) -> None:
        yfinance_bundle = {
            "status": "partial",
            "growth": {"roe": 42.0},
            "earnings": {"dividend": {"ttm_cash_dividend_per_share": 1.0}},
            "belong_boards": [{"name": "Technology", "type": "行业"}],
            "source_chain": [{"provider": "yfinance", "result": "partial"}],
            "errors": [],
        }
        sec_bundle = {
            "status": "partial",
            "growth": {"revenue_yoy": 16.4},
            "earnings": {"financial_report": {"revenue": 111, "source": "SEC EDGAR Company Facts"}},
            "source_chain": [{"provider": "sec_edgar", "result": "ok"}],
            "errors": [],
        }
        fmp_bundle = {
            "status": "partial",
            "growth": {},
            "earnings": {
                "valuation_metrics": {"ev_to_ebitda_ttm": 24.2},
                "quality_metrics": {"roic_ttm_pct": 61.0},
            },
            "source_chain": [{"provider": "fmp", "result": "partial"}],
            "errors": [],
        }

        merged = DataFetcherManager._merge_offshore_fundamental_bundles(
            yfinance_bundle, sec_bundle, fmp_bundle,
        )

        self.assertEqual(merged["earnings"]["financial_report"]["revenue"], 111)
        self.assertEqual(merged["earnings"]["valuation_metrics"]["ev_to_ebitda_ttm"], 24.2)
        self.assertEqual(merged["earnings"]["dividend"]["ttm_cash_dividend_per_share"], 1.0)
        self.assertEqual(merged["provider"], "sec_edgar+yfinance+fmp")
        self.assertEqual(len(merged["source_chain"]), 3)

    def test_unconfigured_fmp_is_not_scheduled(self) -> None:
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._yfinance_fundamental_adapter = MagicMock()
        manager._sec_edgar_fundamental_adapter = MagicMock()
        manager._fmp_fundamental_adapter = MagicMock()
        manager._fmp_fundamental_adapter.is_configured = False
        manager._yfinance_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "partial", "growth": {}, "earnings": {}, "source_chain": [], "errors": [],
        }
        manager._sec_edgar_fundamental_adapter.get_fundamental_bundle.return_value = {
            "status": "partial", "growth": {}, "earnings": {}, "source_chain": [], "errors": [],
        }

        manager._fetch_offshore_fundamental_bundle("AAPL", include_sec=True, timeout_seconds=1)

        manager._fmp_fundamental_adapter.get_fundamental_bundle.assert_not_called()

    def test_configured_fmp_is_scheduled(self) -> None:
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._yfinance_fundamental_adapter = MagicMock()
        manager._sec_edgar_fundamental_adapter = MagicMock()
        manager._fmp_fundamental_adapter = MagicMock()
        manager._fmp_fundamental_adapter.is_configured = True
        for adapter in (
            manager._yfinance_fundamental_adapter,
            manager._sec_edgar_fundamental_adapter,
            manager._fmp_fundamental_adapter,
        ):
            adapter.get_fundamental_bundle.return_value = {
                "status": "partial", "growth": {}, "earnings": {}, "source_chain": [], "errors": [],
            }

        manager._fetch_offshore_fundamental_bundle("AAPL", include_sec=True, timeout_seconds=1)

        manager._fmp_fundamental_adapter.get_fundamental_bundle.assert_called_once_with("AAPL")


class TestFmpPromptWiring(unittest.TestCase):
    def test_fmp_metrics_are_injected_into_analysis_prompt(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_skill_prompt_sections = MagicMock(return_value=("", "", True))
        analyzer._get_runtime_config = MagicMock(
            return_value=SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        )
        analyzer._format_volume = MagicMock(return_value="0")
        analyzer._format_amount = MagicMock(return_value="0")
        context = {
            "code": "AAPL",
            "today": {"close": 200, "pct_chg": 1.0, "volume": 1, "amount": 1},
            "fundamental_context": {
                "earnings": {
                    "data": {
                        "valuation_metrics": {"ev_to_ebitda_ttm": 24.2},
                        "quality_metrics": {"roic_ttm_pct": 61.0},
                        "financial_health": {"debt_to_equity_ttm": 1.87},
                    }
                }
            },
        }

        prompt = analyzer._format_prompt(context, "Apple Inc.", report_language="zh")

        self.assertIn("FMP估值与质量指标", prompt)
        self.assertIn("24.2", prompt)
        self.assertIn("61.0", prompt)
        self.assertIn("1.87", prompt)


if __name__ == "__main__":
    unittest.main()
