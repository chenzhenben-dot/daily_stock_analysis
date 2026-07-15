# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from data_provider.fred_macro_adapter import FredMacroAdapter


class FredMacroAdapterTest(unittest.TestCase):
    def test_fetch_snapshot_uses_latest_two_valid_observations(self) -> None:
        calls = []

        def fetch_csv(series_id: str) -> str:
            calls.append(series_id)
            return (
                f"observation_date,{series_id}\n"
                "2026-07-08,4.50\n"
                "2026-07-09,.\n"
                "2026-07-10,4.56\n"
            )

        adapter = FredMacroAdapter(fetch_csv=fetch_csv, series_ids=("DGS10",))
        snapshot = adapter.fetch_snapshot()

        self.assertEqual(calls, ["DGS10"])
        self.assertEqual(snapshot[0]["series_id"], "DGS10")
        self.assertEqual(snapshot[0]["value"], 4.56)
        self.assertEqual(snapshot[0]["previous_value"], 4.5)
        self.assertEqual(snapshot[0]["change"], 0.06)
        self.assertEqual(snapshot[0]["observation_date"], "2026-07-10")
        self.assertEqual(snapshot[0]["source"], "FRED")

    def test_fetch_snapshot_is_fail_open_per_series(self) -> None:
        def fetch_csv(series_id: str) -> str:
            if series_id == "DGS2":
                raise TimeoutError("slow")
            return f"observation_date,{series_id}\n2026-07-10,4.56\n"

        adapter = FredMacroAdapter(fetch_csv=fetch_csv, series_ids=("DGS2", "DGS10"))
        snapshot = adapter.fetch_snapshot()

        self.assertEqual([item["series_id"] for item in snapshot], ["DGS10"])

    def test_fetch_snapshot_reuses_ttl_cache(self) -> None:
        calls = 0

        def fetch_csv(series_id: str) -> str:
            nonlocal calls
            calls += 1
            return f"observation_date,{series_id}\n2026-07-10,1.0\n"

        adapter = FredMacroAdapter(
            fetch_csv=fetch_csv,
            series_ids=("DFF",),
            cache_ttl_seconds=3600,
        )

        self.assertEqual(adapter.fetch_snapshot(), adapter.fetch_snapshot())
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
