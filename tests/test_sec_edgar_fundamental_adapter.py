from __future__ import annotations

import unittest
import sys
from unittest.mock import MagicMock

if "fake_useragent" not in sys.modules:
    sys.modules["fake_useragent"] = MagicMock()

from data_provider.sec_edgar_fundamental_adapter import SecEdgarFundamentalAdapter
from data_provider.base import DataFetcherManager


class TestSecEdgarFundamentalAdapter(unittest.TestCase):
    def _request_json(self, url: str):
        if url.endswith("company_tickers.json"):
            return {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        if "submissions" in url and url.endswith("CIK0000320193.json"):
            return {
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-26-000010", "0000320193-25-000123"],
                        "filingDate": ["2026-05-01", "2025-10-31"],
                        "reportDate": ["2026-03-28", "2025-09-27"],
                        "form": ["10-Q", "10-K"],
                        "primaryDocument": ["aapl-20260328.htm", "aapl-20250927.htm"],
                    }
                }
            }
        if "companyfacts" in url and url.endswith("CIK0000320193.json"):
            def fact(values):
                return {"units": {"USD": values}}

            return {
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": fact([
                            {"end": "2025-03-29", "val": 95359000000, "form": "10-Q", "fp": "Q2", "filed": "2025-05-02", "accn": "old"},
                            {"end": "2026-03-28", "val": 111000000000, "form": "10-Q", "fp": "Q2", "filed": "2026-05-01", "accn": "new"},
                        ]),
                        "NetIncomeLoss": fact([
                            {"end": "2025-03-29", "val": 24780000000, "form": "10-Q", "fp": "Q2", "filed": "2025-05-02", "accn": "old"},
                            {"end": "2026-03-28", "val": 29500000000, "form": "10-Q", "fp": "Q2", "filed": "2026-05-01", "accn": "new"},
                        ]),
                        "NetCashProvidedByUsedInOperatingActivities": fact([
                            {"end": "2026-03-28", "val": 28700000000, "form": "10-Q", "fp": "Q2", "filed": "2026-05-01", "accn": "new"},
                        ]),
                        "GrossProfit": fact([
                            {"end": "2026-03-28", "val": 53200000000, "form": "10-Q", "fp": "Q2", "filed": "2026-05-01", "accn": "new"},
                        ]),
                    }
                },
            }
        raise AssertionError(url)

    def test_builds_official_financial_bundle(self) -> None:
        adapter = SecEdgarFundamentalAdapter(request_json=self._request_json)

        bundle = adapter.get_fundamental_bundle("AAPL")

        self.assertEqual(bundle["status"], "partial")
        report = bundle["earnings"]["financial_report"]
        self.assertEqual(report["report_date"], "2026-03-28")
        self.assertEqual(report["revenue"], 111000000000)
        self.assertEqual(report["net_profit_parent"], 29500000000)
        self.assertEqual(report["operating_cash_flow"], 28700000000)
        self.assertEqual(report["form"], "10-Q")
        self.assertEqual(report["source"], "SEC EDGAR Company Facts")
        self.assertAlmostEqual(bundle["growth"]["revenue_yoy"], 16.4, places=1)
        self.assertAlmostEqual(bundle["growth"]["net_profit_yoy"], 19.0, places=1)
        self.assertAlmostEqual(bundle["growth"]["gross_margin"], 47.93, places=1)
        self.assertEqual(bundle["earnings"]["sec_filings"][0]["form"], "10-Q")

    def test_non_us_symbol_is_not_supported(self) -> None:
        bundle = SecEdgarFundamentalAdapter(request_json=self._request_json).get_fundamental_bundle("0700.HK")
        self.assertEqual(bundle["status"], "not_supported")

    def test_network_failure_is_fail_open(self) -> None:
        def fail(_url: str):
            raise TimeoutError("SEC timeout")

        bundle = SecEdgarFundamentalAdapter(request_json=fail).get_fundamental_bundle("AAPL")
        self.assertEqual(bundle["status"], "not_supported")
        self.assertTrue(bundle["errors"])


class TestSecEdgarBundleMerge(unittest.TestCase):
    def test_sec_financials_override_yfinance_but_keep_dividends_and_boards(self) -> None:
        yfinance_bundle = {
            "status": "partial",
            "growth": {"revenue_yoy": 9.0, "roe": 42.0},
            "earnings": {
                "financial_report": {"revenue": 90, "source": "yfinance"},
                "dividend": {"ttm_cash_dividend_per_share": 1.0},
            },
            "belong_boards": [{"name": "Technology", "type": "行业"}],
            "source_chain": ["earnings:yfinance"],
            "errors": [],
        }
        sec_bundle = {
            "status": "partial",
            "growth": {"revenue_yoy": 16.4},
            "earnings": {
                "financial_report": {"revenue": 111, "source": "SEC EDGAR Company Facts"},
                "sec_filings": [{"form": "10-Q"}],
            },
            "source_chain": [{"provider": "sec_edgar", "result": "ok"}],
            "errors": [],
        }

        merged = DataFetcherManager._merge_offshore_fundamental_bundles(
            yfinance_bundle,
            sec_bundle,
        )

        self.assertEqual(merged["earnings"]["financial_report"]["revenue"], 111)
        self.assertEqual(merged["earnings"]["dividend"]["ttm_cash_dividend_per_share"], 1.0)
        self.assertEqual(merged["growth"]["revenue_yoy"], 16.4)
        self.assertEqual(merged["growth"]["roe"], 42.0)
        self.assertEqual(merged["belong_boards"][0]["name"], "Technology")
        self.assertEqual(len(merged["source_chain"]), 2)


if __name__ == "__main__":
    unittest.main()
