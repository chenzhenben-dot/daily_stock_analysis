from __future__ import annotations

import unittest

import pandas as pd

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


if __name__ == "__main__":
    unittest.main()
