# -*- coding: utf-8 -*-
"""Official FRED macro snapshot for US market reviews (fail-open, no API key)."""
from __future__ import annotations

import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import StringIO
from threading import RLock
from time import monotonic
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_DEFAULT_SERIES = (
    "DFF",
    "DGS2",
    "DGS10",
    "T10Y2Y",
    "VIXCLS",
    "BAMLH0A0HYM2",
    "UNRATE",
    "CPIAUCSL",
)
_SERIES_META: Dict[str, Dict[str, str]] = {
    "DFF": {"name_zh": "联邦基金有效利率", "name_en": "Effective Federal Funds Rate", "unit": "%"},
    "DGS2": {"name_zh": "美国2年期国债收益率", "name_en": "2-Year Treasury Yield", "unit": "%"},
    "DGS10": {"name_zh": "美国10年期国债收益率", "name_en": "10-Year Treasury Yield", "unit": "%"},
    "T10Y2Y": {"name_zh": "美债10年-2年期限利差", "name_en": "10Y-2Y Treasury Spread", "unit": "%"},
    "VIXCLS": {"name_zh": "VIX恐慌指数", "name_en": "VIX", "unit": ""},
    "BAMLH0A0HYM2": {"name_zh": "美国高收益债利差", "name_en": "US High Yield Spread", "unit": "%"},
    "UNRATE": {"name_zh": "美国失业率", "name_en": "US Unemployment Rate", "unit": "%"},
    "CPIAUCSL": {"name_zh": "美国CPI指数", "name_en": "US CPI Index", "unit": "index"},
}


class FredMacroAdapter:
    """Fetch a compact, cached macro snapshot from FRED's public CSV endpoint."""

    def __init__(
        self,
        fetch_csv: Optional[Callable[[str], str]] = None,
        series_ids: Sequence[str] = _DEFAULT_SERIES,
        timeout_seconds: float = 5.0,
        cache_ttl_seconds: float = 21600,
    ) -> None:
        self.series_ids = tuple(series_id for series_id in series_ids if series_id in _SERIES_META)
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self._fetch_csv = fetch_csv or self._http_csv
        self._cache: List[Dict[str, Any]] = []
        self._cache_at = 0.0
        self._cache_lock = RLock()

    def _http_csv(self, series_id: str) -> str:
        start_date = (date.today() - timedelta(days=450)).isoformat()
        query = urlencode({"id": series_id, "cosd": start_date})
        request = Request(
            f"{_CSV_URL}?{query}",
            headers={"User-Agent": "daily-stock-analysis/3.26", "Accept": "text/csv"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8-sig")

    @staticmethod
    def _parse_value(value: Any) -> Optional[float]:
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed == parsed else None

    def _fetch_series(self, series_id: str) -> Optional[Dict[str, Any]]:
        content = self._fetch_csv(series_id)
        observations = []
        for row in csv.DictReader(StringIO(content)):
            value = self._parse_value(row.get(series_id))
            observation_date = str(row.get("observation_date") or row.get("DATE") or "").strip()
            if value is not None and observation_date:
                observations.append((observation_date, value))
        if not observations:
            return None

        observations.sort(key=lambda item: item[0])
        latest_date, latest_value = observations[-1]
        previous_value = observations[-2][1] if len(observations) > 1 else None
        meta = _SERIES_META[series_id]
        return {
            "series_id": series_id,
            "name_zh": meta["name_zh"],
            "name_en": meta["name_en"],
            "value": latest_value,
            "previous_value": previous_value,
            "change": round(latest_value - previous_value, 4) if previous_value is not None else None,
            "unit": meta["unit"],
            "observation_date": latest_date,
            "source": "FRED",
        }

    def fetch_snapshot(self) -> List[Dict[str, Any]]:
        now = monotonic()
        with self._cache_lock:
            if self._cache and now - self._cache_at <= self.cache_ttl_seconds:
                return [dict(item) for item in self._cache]

        results: Dict[str, Dict[str, Any]] = {}
        max_workers = min(4, len(self.series_ids)) or 1
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fred") as executor:
            futures = {executor.submit(self._fetch_series, series_id): series_id for series_id in self.series_ids}
            for future in as_completed(futures):
                series_id = futures[future]
                try:
                    item = future.result()
                except Exception as exc:
                    logger.warning("[FRED] series=%s status=failed error=%s", series_id, exc)
                    continue
                if item:
                    results[series_id] = item

        snapshot = [results[series_id] for series_id in self.series_ids if series_id in results]
        if snapshot:
            with self._cache_lock:
                self._cache = [dict(item) for item in snapshot]
                self._cache_at = now
        return snapshot
