# -*- coding: utf-8 -*-
"""Official SEC EDGAR fundamentals for US equities (fail-open, no API key)."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from threading import RLock
from time import monotonic
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_DEFAULT_USER_AGENT = (
    "daily-stock-analysis/3.26 "
    "admin@ptsuneagleind.com"
)
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_FORM_TYPES = {"10-K", "10-Q"}

_CONCEPTS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_profit_parent": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "gross_profit": ("GrossProfit",),
}


def _safe_float(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _parse_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


class SecEdgarFundamentalAdapter:
    """Build the existing DSA fundamental bundle from SEC Company Facts."""

    _ticker_cache: Dict[str, Dict[str, Any]] = {}
    _ticker_cache_at = 0.0
    _ticker_cache_lock = RLock()

    def __init__(
        self,
        request_json: Optional[Callable[[str], Any]] = None,
        timeout_seconds: float = 6.0,
    ) -> None:
        self.timeout_seconds = max(0.5, float(timeout_seconds))
        self._request_json = request_json or self._http_json

    def _http_json(self, url: str) -> Any:
        user_agent = os.getenv("SEC_EDGAR_USER_AGENT", "").strip() or _DEFAULT_USER_AGENT
        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Host": "data.sec.gov" if "data.sec.gov" in url else "www.sec.gov",
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _normalize_symbol(stock_code: str) -> Optional[str]:
        symbol = str(stock_code or "").strip().upper()
        if symbol.startswith("US."):
            symbol = symbol[3:]
        if not _US_SYMBOL.fullmatch(symbol):
            return None
        if symbol.startswith("^") or any(symbol.endswith(suffix) for suffix in (".HK", ".SS", ".SZ", ".T", ".KS", ".KQ", ".TW", ".TWO")):
            return None
        return symbol

    def _ticker_map(self) -> Dict[str, Dict[str, Any]]:
        ttl = max(300, int(os.getenv("SEC_EDGAR_TICKER_CACHE_TTL_SECONDS", "86400")))
        now = monotonic()
        with self._ticker_cache_lock:
            if self._ticker_cache and now - self._ticker_cache_at <= ttl:
                return dict(self._ticker_cache)

        payload = self._request_json(_TICKER_URL)
        mapping: Dict[str, Dict[str, Any]] = {}
        values = payload.values() if isinstance(payload, dict) else []
        for item in values:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").strip().upper()
            cik = item.get("cik_str")
            if ticker and cik is not None:
                mapping[ticker] = {"cik": f"{int(cik):010d}", "title": item.get("title")}

        with self._ticker_cache_lock:
            self.__class__._ticker_cache = mapping
            self.__class__._ticker_cache_at = now
        return dict(mapping)

    @staticmethod
    def _duration_days(item: Dict[str, Any]) -> Optional[int]:
        start = _parse_date(item.get("start"))
        end = _parse_date(item.get("end"))
        return (end - start).days if start and end else None

    @classmethod
    def _period_score(cls, item: Dict[str, Any]) -> int:
        duration = cls._duration_days(item)
        form = str(item.get("form") or "")
        if duration is None:
            return 0
        target = 91 if form == "10-Q" else 365
        return -abs(duration - target)

    @classmethod
    def _fact_items(cls, facts: Dict[str, Any], concepts: tuple[str, ...]) -> List[Dict[str, Any]]:
        for concept in concepts:
            node = facts.get(concept)
            units = node.get("units") if isinstance(node, dict) else None
            if not isinstance(units, dict):
                continue
            values = units.get("USD")
            if not isinstance(values, list):
                values = next((v for key, v in units.items() if key.startswith("USD") and isinstance(v, list)), [])
            rows = [item for item in values if isinstance(item, dict) and item.get("form") in _FORM_TYPES and _safe_float(item.get("val")) is not None]
            if rows:
                return rows
        return []

    @classmethod
    def _latest_fact(cls, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        return max(rows, key=lambda item: (str(item.get("end") or ""), str(item.get("filed") or ""), cls._period_score(item)))

    @classmethod
    def _yoy(cls, rows: List[Dict[str, Any]], latest: Optional[Dict[str, Any]]) -> Optional[float]:
        if not latest:
            return None
        latest_end = _parse_date(latest.get("end"))
        latest_value = _safe_float(latest.get("val"))
        if latest_end is None or latest_value is None:
            return None
        latest_duration = cls._duration_days(latest)
        candidates = []
        for item in rows:
            end = _parse_date(item.get("end"))
            value = _safe_float(item.get("val"))
            if end is None or value in (None, 0):
                continue
            delta = (latest_end - end).days
            duration = cls._duration_days(item)
            duration_gap = abs((latest_duration or 0) - (duration or 0))
            if 300 <= delta <= 430 and item.get("fp") == latest.get("fp") and duration_gap <= 45:
                candidates.append((abs(delta - 365), duration_gap, item))
        if not candidates:
            return None
        previous = min(candidates, key=lambda value: (value[0], value[1]))[2]
        previous_value = _safe_float(previous.get("val"))
        if previous_value in (None, 0):
            return None
        return round((latest_value - previous_value) / abs(previous_value) * 100.0, 4)

    @staticmethod
    def _recent_filings(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        recent = ((payload.get("filings") or {}).get("recent") or {}) if isinstance(payload, dict) else {}
        forms = recent.get("form") if isinstance(recent, dict) else None
        if not isinstance(forms, list):
            return []
        fields = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
        rows = []
        for index, form in enumerate(forms):
            if form not in {"10-K", "10-Q", "8-K"}:
                continue
            item = {field: (recent.get(field) or [None] * len(forms))[index] for field in fields}
            accession = str(item.get("accessionNumber") or "").replace("-", "")
            document = item.get("primaryDocument")
            if accession and document:
                item["url"] = f"https://www.sec.gov/Archives/edgar/data/{int(str(payload.get('cik') or 0) or 0)}/{accession}/{document}"
            rows.append({
                "form": item.get("form"),
                "filing_date": item.get("filingDate"),
                "report_date": item.get("reportDate"),
                "accession_number": item.get("accessionNumber"),
                "primary_document": document,
                "url": item.get("url"),
            })
            if len(rows) >= 8:
                break
        return rows

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "source_chain": [],
            "errors": [],
        }
        symbol = self._normalize_symbol(stock_code)
        if not symbol:
            return result

        try:
            company = self._ticker_map().get(symbol)
            if not company:
                result["errors"].append(f"ticker_not_found:{symbol}")
                return result
            cik = company["cik"]
            facts_payload = self._request_json(_FACTS_URL.format(cik=cik))
            submissions_payload = self._request_json(_SUBMISSIONS_URL.format(cik=cik))
            if isinstance(submissions_payload, dict):
                submissions_payload.setdefault("cik", cik)

            facts = ((facts_payload.get("facts") or {}).get("us-gaap") or {}) if isinstance(facts_payload, dict) else {}
            selected: Dict[str, Optional[Dict[str, Any]]] = {}
            rows_by_key: Dict[str, List[Dict[str, Any]]] = {}
            for key, concepts in _CONCEPTS.items():
                rows = self._fact_items(facts, concepts)
                rows_by_key[key] = rows
                selected[key] = self._latest_fact(rows)

            revenue = selected.get("revenue")
            net_profit = selected.get("net_profit_parent")
            cash_flow = selected.get("operating_cash_flow")
            gross_profit = selected.get("gross_profit")
            revenue_value = _safe_float((revenue or {}).get("val"))
            gross_profit_value = _safe_float((gross_profit or {}).get("val"))
            gross_margin = None
            if revenue_value not in (None, 0) and gross_profit_value is not None and (gross_profit or {}).get("end") == (revenue or {}).get("end"):
                gross_margin = round(gross_profit_value / revenue_value * 100.0, 4)

            growth = {
                "revenue_yoy": self._yoy(rows_by_key["revenue"], revenue),
                "net_profit_yoy": self._yoy(rows_by_key["net_profit_parent"], net_profit),
                "gross_margin": gross_margin,
            }
            growth = {key: value for key, value in growth.items() if value is not None}
            if growth:
                result["growth"] = growth

            anchor = revenue or net_profit or cash_flow
            financial_report = {
                "report_date": (anchor or {}).get("end"),
                "revenue": revenue_value,
                "net_profit_parent": _safe_float((net_profit or {}).get("val")),
                "operating_cash_flow": _safe_float((cash_flow or {}).get("val")),
                "gross_margin": gross_margin,
                "currency": "USD",
                "form": (anchor or {}).get("form"),
                "fiscal_period": (anchor or {}).get("fp"),
                "filed_at": (anchor or {}).get("filed"),
                "accession_number": (anchor or {}).get("accn"),
                "source": "SEC EDGAR Company Facts",
            }
            financial_report = {key: value for key, value in financial_report.items() if value is not None}
            filings = self._recent_filings(submissions_payload)
            earnings = {}
            if any(key in financial_report for key in ("revenue", "net_profit_parent", "operating_cash_flow")):
                earnings["financial_report"] = financial_report
            if filings:
                earnings["sec_filings"] = filings
            if earnings:
                result["earnings"] = earnings

            if growth or earnings:
                result["status"] = "partial"
                result["source_chain"] = [
                    {"provider": "sec_edgar", "result": "ok", "dataset": "companyfacts+submissions"}
                ]
        except Exception as exc:
            result["errors"].append(f"sec_edgar:{type(exc).__name__}:{exc}")
            logger.warning("[SEC EDGAR] %s fundamentals failed: %s", symbol, exc)
        return result
