# -*- coding: utf-8 -*-
"""Regression tests for TickFlow market-review manager fallback."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if "fake_useragent" not in sys.modules:
    sys.modules["fake_useragent"] = MagicMock()

from data_provider.base import DataFetcherManager


class _DummyFetcher:
    def __init__(self, name, indices=None, stats=None):
        self.name = name
        self.priority = 1
        self.indices = indices
        self.stats = stats
        self.index_calls = 0
        self.stats_calls = 0

    def get_main_indices(self, region="cn"):
        self.index_calls += 1
        return self.indices

    def get_market_stats(self):
        self.stats_calls += 1
        return self.stats


class _DummyTickFlowFetcher:
    def __init__(self, indices=None, stats=None, error=None):
        self.indices = indices
        self.stats = stats
        self.error = error
        self.closed = False

    def get_main_indices(self, region="cn"):
        if self.error is not None:
            raise self.error
        return self.indices

    def get_market_stats(self):
        if self.error is not None:
            raise self.error
        return self.stats

    def close(self):
        self.closed = True


class TestTickFlowMarketReviewFallback(unittest.TestCase):
    def test_manager_prefers_tickflow_indices_when_available(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher("AkshareFetcher", indices=[{"code": "fallback"}])
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            indices=[{"code": "000001"}]
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(data, [{"code": "000001"}])
        self.assertEqual(fallback.index_calls, 0)

    def test_manager_falls_back_when_tickflow_indices_fail(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher("AkshareFetcher", indices=[{"code": "fallback"}])
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            error=RuntimeError("tickflow down")
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(data, [{"code": "fallback"}])
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_falls_back_when_tickflow_indices_missing(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher("AkshareFetcher", indices=[{"code": "fallback"}])
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            indices=None
        )

        data = DataFetcherManager.get_main_indices(manager, region="cn")

        self.assertEqual(data, [{"code": "fallback"}])
        self.assertEqual(fallback.index_calls, 1)

    def test_manager_skips_tickflow_for_non_cn_indices(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher("YfinanceFetcher", indices=[{"code": "^GSPC"}])
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should not be called for non-CN indices"
        )

        data = DataFetcherManager.get_main_indices(manager, region="us")

        self.assertEqual(data, [{"code": "^GSPC"}])
        self.assertEqual(fallback.index_calls, 1)

    def test_us_market_stats_uses_moomoo_and_skips_tickflow(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        moomoo = _DummyFetcher(
            "MoomooFetcher",
            stats={"up_count": 7, "down_count": 3, "flat_count": 1},
        )
        manager._fetchers = [moomoo]
        manager._get_fetchers_snapshot = lambda: [moomoo]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should not be called for US market stats"
        )

        data = DataFetcherManager.get_market_stats(manager, purpose="market_review:us")

        self.assertEqual(data["up_count"], 7)
        self.assertEqual(moomoo.stats_calls, 1)

    def test_us_market_stats_does_not_fall_back_to_cn_sources(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        moomoo = _DummyFetcher("MoomooFetcher", stats=None)
        cn_fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 4000, "down_count": 1000, "flat_count": 200},
        )
        manager._fetchers = [moomoo, cn_fallback]
        manager._get_fetchers_snapshot = lambda: [moomoo, cn_fallback]
        manager._get_tickflow_fetcher = lambda: self.fail(
            "TickFlow should not be called for US market stats"
        )

        data = DataFetcherManager.get_market_stats(manager, purpose="market_review:us")

        self.assertEqual(data, {})
        self.assertEqual(moomoo.stats_calls, 1)
        self.assertEqual(cn_fallback.stats_calls, 0)

    def test_manager_falls_back_when_tickflow_market_stats_fails(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 1, "down_count": 2, "flat_count": 3},
        )
        manager._fetchers = [fallback]
        manager._get_tickflow_fetcher = lambda: _DummyTickFlowFetcher(
            error=RuntimeError("tickflow down")
        )

        data = DataFetcherManager.get_market_stats(manager, purpose="market_review:cn")

        self.assertEqual(data["up_count"], 1)
        self.assertEqual(fallback.stats_calls, 1)

    def test_cn_market_stats_never_uses_us_only_moomoo_stats(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        moomoo = _DummyFetcher(
            "MoomooFetcher",
            stats={
                "up_count": 819,
                "down_count": 1063,
                "total_amount": 179599561831,
                "source": "moomoo_us_exchange_universe",
            },
        )
        cn_fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 3200, "down_count": 1800, "total_amount": 18000},
        )
        manager._fetchers = [moomoo, cn_fallback]
        manager._get_tickflow_fetcher = lambda: None

        data = DataFetcherManager.get_market_stats(manager, purpose="market_review:cn")

        self.assertEqual(data["up_count"], 3200)
        self.assertEqual(moomoo.stats_calls, 0)
        self.assertEqual(cn_fallback.stats_calls, 1)

    @patch("src.config.get_config")
    def test_manager_skips_tickflow_without_api_key(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(tickflow_api_key=None)

        manager = DataFetcherManager.__new__(DataFetcherManager)
        fallback = _DummyFetcher(
            "AkshareFetcher",
            stats={"up_count": 2, "down_count": 1, "flat_count": 0},
        )
        manager._fetchers = [fallback]

        data = DataFetcherManager.get_market_stats(manager)

        self.assertEqual(data["up_count"], 2)
        self.assertEqual(fallback.stats_calls, 1)

    def test_manager_close_releases_tickflow_fetcher(self):
        manager = DataFetcherManager.__new__(DataFetcherManager)
        tickflow_fetcher = _DummyTickFlowFetcher(indices=[{"code": "000001"}])
        manager._tickflow_fetcher = tickflow_fetcher
        manager._tickflow_api_key = "tf-secret"
        manager._tickflow_lock = None

        DataFetcherManager.close(manager)

        self.assertTrue(tickflow_fetcher.closed)
        self.assertIsNone(manager._tickflow_fetcher)
        self.assertIsNone(manager._tickflow_api_key)


if __name__ == "__main__":
    unittest.main()
