from __future__ import annotations

import unittest
import sys
from unittest.mock import MagicMock

import pandas as pd

if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

from data_provider.moomoo_fetcher import MoomooFetcher, RET_OK
from data_provider.realtime_types import RealtimeSource


class _SnapshotContext:
    def __init__(self) -> None:
        self.snapshot_codes = None

    def get_market_snapshot(self, codes):
        self.snapshot_codes = codes
        return RET_OK, pd.DataFrame(
            [
                {
                    "code": "US.GRAB",
                    "name": "Grab Holdings",
                    "update_time": "2026-07-17 20:01:23.601",
                    "last_price": 3.80,
                    "volume": 12_345_678,
                    "turnover_rate": 0.42,
                    "open_price": 3.76,
                    "high_price": 3.83,
                    "low_price": 3.72,
                    "prev_close_price": 3.74,
                    "pe_ratio": 63.333,
                    "pb_ratio": 2.385,
                    "total_market_val": 15_542_000_000,
                    "circular_market_val": 10_122_190_701,
                }
            ]
        )

    def get_stock_quote(self, _codes):
        raise AssertionError("get_stock_quote requires a prior subscription")


class _MarketStatsContext:
    def __init__(self) -> None:
        self.filter_calls = []
        self.snapshot_calls = []

    def get_stock_filter(self, market, filter_list, plate_code=None, begin=0, num=200):
        self.filter_calls.append(
            {
                "market": market,
                "filter_list": filter_list,
                "plate_code": plate_code,
                "begin": begin,
                "num": num,
            }
        )
        if plate_code == "US.NYSE":
            return RET_OK, (
                True,
                2,
                [
                    {"stock_code": "US.AAA"},
                    {"stock_code": "US.BBB"},
                ],
            )
        if plate_code == "US.NASDAQ":
            return RET_OK, (
                True,
                2,
                [
                    {"code": "US.CCC"},
                    {"code": "US.AAA"},
                ],
            )
        return RET_OK, (True, 0, [])

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        rows = []
        data = {
            "US.AAA": {"last_price": 11.0, "prev_close_price": 10.0, "turnover": 1000.0},
            "US.BBB": {"last_price": 9.0, "prev_close_price": 10.0, "turnover": 2000.0},
            "US.CCC": {"last_price": 10.1, "prev_close_price": 10.0, "turnover": 3000.0},
        }
        for code in codes:
            if code in data:
                rows.append({"code": code, **data[code]})
        return RET_OK, pd.DataFrame(rows)


class MoomooRealtimeQuoteTest(unittest.TestCase):
    def test_realtime_quote_uses_snapshot_without_subscription(self) -> None:
        context = _SnapshotContext()
        fetcher = MoomooFetcher.__new__(MoomooFetcher)
        fetcher._disabled_reason = None
        fetcher._ctx = context
        fetcher._ensure_ctx = lambda: context

        quote = fetcher.get_realtime_quote("GRAB")

        self.assertEqual(["US.GRAB"], context.snapshot_codes)
        self.assertIsNotNone(quote)
        self.assertEqual("Grab Holdings", quote.name)
        self.assertEqual(RealtimeSource.MOOMOO, quote.source)
        self.assertEqual(3.80, quote.price)
        self.assertAlmostEqual(1.604278, quote.change_pct, places=5)
        self.assertAlmostEqual(0.06, quote.change_amount, places=6)
        self.assertEqual("2026-07-17T20:01:23.601000-04:00", quote.provider_timestamp)
        self.assertEqual("us", quote.market)
        self.assertEqual("USD", quote.currency)
        self.assertIsInstance(quote.volume, int)
        self.assertEqual(15_542_000_000, quote.total_mv)
        self.assertEqual(10_122_190_701, quote.circ_mv)


class MoomooMarketStatsTest(unittest.TestCase):
    def test_market_stats_aggregates_us_exchange_universe_snapshots(self) -> None:
        context = _MarketStatsContext()
        fetcher = MoomooFetcher.__new__(MoomooFetcher)
        fetcher._disabled_reason = None
        fetcher._ctx = context
        fetcher._ensure_ctx = lambda: context

        stats = fetcher.get_market_stats()

        self.assertIsNotNone(stats)
        self.assertEqual(2, stats["up_count"])
        self.assertEqual(1, stats["down_count"])
        self.assertEqual(0, stats["flat_count"])
        self.assertEqual(6000.0, stats["total_amount"])
        self.assertEqual(3, stats["sample_size"])
        self.assertEqual("moomoo_us_exchange_universe", stats["source"])
        self.assertEqual(["US.AAA", "US.BBB", "US.CCC"], context.snapshot_calls[0])
        self.assertEqual(
            ["US.NYSE", "US.NASDAQ", "US.AMEX"],
            [call["plate_code"] for call in context.filter_calls],
        )


if __name__ == "__main__":
    unittest.main()
