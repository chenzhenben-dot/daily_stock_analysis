from __future__ import annotations

import unittest

import pandas as pd

from data_provider.moomoo_fetcher import MoomooFetcher, RET_OK


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
                    "last_price": 3.80,
                    "change_rate": 1.60,
                    "change_val": 0.06,
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
        self.assertEqual(3.80, quote.price)
        self.assertEqual(1.60, quote.change_pct)
        self.assertEqual(15_542_000_000, quote.total_mv)
        self.assertEqual(10_122_190_701, quote.circ_mv)


if __name__ == "__main__":
    unittest.main()