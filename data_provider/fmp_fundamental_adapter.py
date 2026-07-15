# -*- coding: utf-8 -*-
"""Financial Modeling Prep valuation and quality metrics for US equities."""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_BASE_URL = "https://financialmodelingprep.com/stable"
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


def _number(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _first_number(payloads: List[Dict[str, Any]], *keys: str) -> Optional[float]:
    for payload in payloads:
        for key in keys:
            value = _number(payload.get(key))
            if value is not None:
                return value
    return None


def _percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    normalized = value * 100.0 if abs(value) <= 1.0 else value
    return round(normalized, 4)


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != ""}


class FmpFundamentalAdapter:
    """Fetch additive FMP TTM metrics; disabled silently when no key is configured."""

    _cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
    _cache_lock = RLock()

    def __init__(
        self,
        api_key: Optional[str] = None,
        request_json: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        timeout_seconds: float = 6.0,
        cache_ttl_seconds: Optional[float] = None,
    ) -> None:
        self.api_key = (
            api_key
            if api_key is not None
            else os.getenv("FMP_API_KEY") or os.getenv("FINANCIAL_MODELING_PREP_API_KEY") or ""
        ).strip()
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        configured_ttl = os.getenv("FMP_CACHE_TTL_SECONDS", "21600")
        self.cache_ttl_seconds = max(
            0.0,
            float(configured_ttl if cache_ttl_seconds is None else cache_ttl_seconds),
        )
        self._request_json = request_json or self._http_json

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _http_json(self, path: str, params: Dict[str, Any]) -> Any:
        query = dict(params)
        query["apikey"] = self.api_key
        request = Request(
            f"{_BASE_URL}/{path}?{urlencode(query)}",
            headers={"User-Agent": "daily-stock-analysis/3.26", "Accept": "application/json"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and (payload.get("Error Message") or payload.get("error")):
            raise ValueError(str(payload.get("Error Message") or payload.get("error")))
        return payload

    @staticmethod
    def _normalize_symbol(stock_code: str) -> Optional[str]:
        symbol = str(stock_code or "").strip().upper()
        if symbol.startswith("US."):
            symbol = symbol[3:]
        if not _US_SYMBOL.fullmatch(symbol):
            return None
        if symbol.startswith("^") or any(
            symbol.endswith(suffix)
            for suffix in (".HK", ".SS", ".SZ", ".T", ".KS", ".KQ", ".TW", ".TWO")
        ):
            return None
        return symbol

    @staticmethod
    def _first_record(payload: Any) -> Dict[str, Any]:
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        if isinstance(payload, dict) and not (payload.get("Error Message") or payload.get("error")):
            return payload
        return {}

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        symbol = self._normalize_symbol(stock_code)
        empty = {
            "provider": "fmp",
            "growth": {},
            "earnings": {},
            "company_profile": {},
            "belong_boards": [],
            "source_chain": [],
            "errors": [],
        }
        if not symbol:
            return {**empty, "status": "not_supported"}
        if not self.is_configured:
            return {**empty, "status": "not_configured"}

        now = monotonic()
        with self._cache_lock:
            cached = self._cache.get(symbol)
            if cached and now - cached[0] <= self.cache_ttl_seconds:
                return deepcopy(cached[1])

        endpoints = ("profile", "ratios-ttm", "key-metrics-ttm")
        records: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="fmp") as executor:
            futures = {
                executor.submit(self._request_json, path, {"symbol": symbol}): path
                for path in endpoints
            }
            for future in as_completed(futures):
                path = futures[future]
                try:
                    record = self._first_record(future.result())
                    if record:
                        records[path] = record
                    else:
                        errors.append(f"{path}:empty")
                except Exception as exc:
                    errors.append(f"{path}:{type(exc).__name__}:{exc}")

        profile = records.get("profile", {})
        metrics = [records.get("ratios-ttm", {}), records.get("key-metrics-ttm", {})]
        valuation = _compact({
            "pe_ratio_ttm": _first_number(metrics, "priceEarningsRatioTTM", "priceToEarningsRatioTTM"),
            "pb_ratio_ttm": _first_number(metrics, "priceToBookRatioTTM"),
            "price_to_sales_ttm": _first_number(metrics, "priceToSalesRatioTTM"),
            "ev_to_sales_ttm": _first_number(metrics, "evToSalesTTM"),
            "ev_to_ebitda_ttm": (
                _first_number(metrics, "evToEBITDATTM")
                if _first_number(metrics, "evToEBITDATTM") is not None
                else _first_number(metrics, "enterpriseValueMultipleTTM")
            ),
            "earnings_yield_ttm_pct": _percent(_first_number(metrics, "earningsYieldTTM")),
            "free_cash_flow_yield_ttm_pct": _percent(_first_number(metrics, "freeCashFlowYieldTTM")),
            "market_cap": _first_number(metrics, "marketCap"),
            "enterprise_value_ttm": _first_number(metrics, "enterpriseValueTTM"),
        })
        quality = _compact({
            "roe_ttm_pct": _percent(_first_number(metrics, "returnOnEquityTTM")),
            "roic_ttm_pct": _percent(_first_number(metrics, "roicTTM", "returnOnInvestedCapitalTTM")),
            "gross_margin_ttm_pct": _percent(_first_number(metrics, "grossProfitMarginTTM")),
            "operating_margin_ttm_pct": _percent(_first_number(metrics, "operatingProfitMarginTTM")),
            "net_margin_ttm_pct": _percent(_first_number(metrics, "netProfitMarginTTM")),
        })
        financial_health = _compact({
            "current_ratio_ttm": _first_number(metrics, "currentRatioTTM"),
            "quick_ratio_ttm": _first_number(metrics, "quickRatioTTM"),
            "debt_to_equity_ttm": _first_number(metrics, "debtEquityRatioTTM"),
            "debt_ratio_ttm": _first_number(metrics, "debtRatioTTM"),
            "interest_coverage_ttm": _first_number(metrics, "interestCoverageTTM"),
            "net_debt_to_ebitda_ttm": _first_number(metrics, "netDebtToEBITDATTM"),
        })
        company_profile = _compact({
            "symbol": symbol,
            "company_name": profile.get("companyName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "exchange": profile.get("exchangeShortName") or profile.get("exchange"),
            "country": profile.get("country"),
            "website": profile.get("website"),
            "description": profile.get("description"),
        })
        boards = []
        if profile.get("sector"):
            boards.append({"name": str(profile["sector"]), "type": "行业"})
        if profile.get("industry") and profile.get("industry") != profile.get("sector"):
            boards.append({"name": str(profile["industry"]), "type": "行业"})

        earnings = _compact({
            "valuation_metrics": valuation or None,
            "quality_metrics": quality or None,
            "financial_health": financial_health or None,
        })
        profile_has_data = any(key != "symbol" for key in company_profile)
        has_data = bool(earnings or profile_has_data or boards)
        status = "partial" if has_data else "not_supported"
        bundle = {
            "provider": "fmp",
            "status": status,
            "growth": {},
            "earnings": earnings,
            "company_profile": company_profile,
            "belong_boards": boards,
            "source_chain": [{"provider": "fmp", "result": status, "duration_ms": 0}],
            "errors": errors,
        }
        if has_data and self.cache_ttl_seconds > 0:
            with self._cache_lock:
                self._cache[symbol] = (now, deepcopy(bundle))
        return bundle
