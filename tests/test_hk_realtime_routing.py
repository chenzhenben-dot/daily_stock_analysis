# -*- coding: utf-8 -*-
"""
Regression tests for Hong Kong realtime quote routing.
"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "litellm" not in sys.modules:
    sys.modules["litellm"] = MagicMock()
if "json_repair" not in sys.modules:
    sys.modules["json_repair"] = MagicMock()

from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote


class _DummyFetcher:
    def __init__(self, name: str, priority: int, result=None):
        self.name = name
        self.priority = priority
        self.result = result
        self.calls = []

    def get_realtime_quote(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class TestHKRealtimeRouting(unittest.TestCase):
    """Ensure HK realtime lookup does not fan out into A-share sources."""

    @patch("src.config.get_config")
    def test_manager_routes_hk_suffix_only_to_akshare_once(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="tencent,akshare_sina,efinance,akshare_em,tushare",
        )

        efinance = _DummyFetcher("EfinanceFetcher", 0, result={"should": "not be called"})
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)
        tushare = _DummyFetcher("TushareFetcher", 2, result={"should": "not be called"})

        manager = DataFetcherManager(fetchers=[efinance, akshare, tushare])
        quote = manager.get_realtime_quote("1810.HK")

        self.assertIsNone(quote)
        self.assertEqual(akshare.calls, [(("HK01810",), {"source": "hk"})])
        self.assertEqual(efinance.calls, [])
        self.assertEqual(tushare.calls, [])

    @patch("src.config.get_config")
    def test_manager_prefers_moomoo_for_hk_stock(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="akshare_em",
            realtime_cache_ttl=600,
        )
        moomoo_quote = UnifiedRealtimeQuote(
            code="1810.HK",
            source=RealtimeSource.MOOMOO,
            price=42.0,
            volume_ratio=1.0,
            turnover_rate=0.5,
            pe_ratio=20.0,
            pb_ratio=3.0,
            total_mv=1.0,
            circ_mv=1.0,
            amplitude=2.0,
        )
        moomoo = _DummyFetcher("MoomooFetcher", 0, result=moomoo_quote)
        akshare = _DummyFetcher("AkshareFetcher", 1, result=None)
        manager = DataFetcherManager(fetchers=[moomoo, akshare])

        quote = manager.get_realtime_quote("1810.HK")

        self.assertIs(quote, moomoo_quote)
        self.assertEqual(moomoo.calls, [(('HK01810',), {})])
        self.assertEqual(akshare.calls, [])

    @patch("src.config.get_config")
    def test_manager_falls_back_to_yfinance_when_moomoo_is_unavailable(self, mock_get_config):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="akshare_em",
            realtime_cache_ttl=600,
        )
        yfinance_quote = UnifiedRealtimeQuote(
            code="SNDK",
            source=RealtimeSource.FALLBACK,
            price=1354.82,
            volume_ratio=1.0,
            turnover_rate=0.5,
            pe_ratio=20.0,
            pb_ratio=3.0,
            total_mv=1.0,
            circ_mv=1.0,
            amplitude=2.0,
        )
        moomoo = _DummyFetcher("MoomooFetcher", 0, result=None)
        yfinance = _DummyFetcher("YfinanceFetcher", 1, result=yfinance_quote)
        manager = DataFetcherManager(fetchers=[moomoo, yfinance])

        quote = manager.get_realtime_quote("SNDK")

        self.assertIs(quote, yfinance_quote)
        self.assertEqual(moomoo.calls, [(('SNDK',), {})])
        self.assertEqual(yfinance.calls, [(('SNDK',), {})])
        self.assertEqual("moomoo", quote.fallback_from)

    @patch.object(DataFetcherManager, "_utc_now_iso", return_value="2026-07-19T06:18:47+00:00")
    @patch("src.config.get_config")
    def test_weekend_keeps_latest_us_session_quote_fresh(self, mock_get_config, _mock_now):
        mock_get_config.return_value = SimpleNamespace(
            enable_realtime_quote=True,
            realtime_source_priority="akshare_em",
            realtime_cache_ttl=600,
        )
        moomoo_quote = UnifiedRealtimeQuote(
            code="SNDK",
            source=RealtimeSource.MOOMOO,
            market="us",
            provider_timestamp="2026-07-17T20:01:23-04:00",
            price=1354.82,
            volume_ratio=1.0,
            turnover_rate=0.5,
            pe_ratio=20.0,
            pb_ratio=3.0,
            total_mv=1.0,
            circ_mv=1.0,
            amplitude=2.0,
        )
        manager = DataFetcherManager(
            fetchers=[_DummyFetcher("MoomooFetcher", 0, result=moomoo_quote)]
        )

        quote = manager.get_realtime_quote("SNDK")

        self.assertFalse(quote.is_stale)
        self.assertEqual(109044, quote.stale_seconds)


if __name__ == "__main__":
    unittest.main()
