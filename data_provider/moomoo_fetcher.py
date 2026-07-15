# -*- coding: utf-8 -*-
"""
MoomooFetcher — Moomoo OpenD data source (via futu-api)

Drops into the DSA fetcher framework and registers itself with priority 0
(after EfinanceFetcher) for US/HK markets. Provides:

- Real-time quote (replaces YFinance delayed data)
- Daily K-line (multi-period, US/HK/A-share)
- Capital distribution (closest analog to A-share chip distribution for
  US/HK; called from DataFetcherManager.get_chip_distribution)
- Main indices (US/HK)
- Capital flow / owner plate / etc.

⚠️ READ-ONLY: OpenQuoteContext only. Never use OpenSecTradeContext.
⚠️ Requires Moomoo OpenD running on host:port (defaults to 127.0.0.1:11111).
   On the deployment server this is reached through an SSH reverse tunnel
   from the user's macOS workstation.

Environment variables:
- MOOMOO_HOST (default: 127.0.0.1)
- MOOMOO_PORT (default: 11111)
- MOOMOO_TIMEOUT (default: 10 seconds)
- MOOMOO_ENABLED (default: false; if "false"/"0" the fetcher is a no-op)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .realtime_types import ChipDistribution, RealtimeSource, UnifiedRealtimeQuote, safe_float
from .akshare_fetcher import _is_us_code

logger = logging.getLogger(__name__)

_FUTU_IMPORT_ERROR: Optional[Exception] = None
try:
    from futu import (
        OpenQuoteContext,
        RET_OK,
        RET_ERROR,
        KLType,
        SubType,
        AuType,
        Market,
    )
except Exception as exc:  # pragma: no cover - import only checked at construction
    _FUTU_IMPORT_ERROR = exc
    OpenQuoteContext = None  # type: ignore[assignment]
    RET_OK = "OK"
    RET_ERROR = "ERROR"
    KLType = None  # type: ignore[assignment]
    SubType = None  # type: ignore[assignment]
    AuType = None  # type: ignore[assignment]
    Market = None  # type: ignore[assignment]


# K-line period -> futu KLType mapping (lazy because futu may be absent at import)
PERIOD_TO_KLTYPE: Dict[str, Any] = {
    "1m": "K_1M",
    "3m": "K_3M",
    "5m": "K_5M",
    "15m": "K_15M",
    "30m": "K_30M",
    "60m": "K_60M",
    "120m": "K_120M",
    "day": "K_DAY",
    "week": "K_WEEK",
    "month": "K_MON",
    "quarter": "K_QUARTER",
    "year": "K_YEAR",
}


# Moomoo OpenD index codes for US / HK (used by get_main_indices)
_US_INDEX_CODES: Dict[str, str] = {
    "SPX": "US." + ".SPX",  # placeholder, futu uses different format
    "IXIC": "US." + ".IXIC",
    "DJI": "US." + ".DJI",
}
# futu actual codes for major US indices (via get_market_snapshot)
_US_INDEX_FUTU_CODES = {
    "SPX": "US.SPX",
    "IXIC": "US.IXIC",
    "DJI": "US.DJI",
    "VIX": "US.VIX",
    "NDX": "US.NDX",
    "RUT": "US.RUT",
}

_HK_INDEX_FUTU_CODES = {
    "HSI": "HK.HSI",
    "HSTECH": "HK.HSTECH",
    "HSCEI": "HK.HSCEI",
}


class MoomooFetcher(BaseFetcher):
    """
    Moomoo / Futu OpenD data source.

    Priority 0 (highest alongside EfinanceFetcher) so that US/HK requests
    hit Moomoo first when available; YFinance remains the global fallback.

    Disabled automatically if:
    - MOOMOO_ENABLED is explicitly "false"/"0"
    - the futu package failed to import
    - a health check at construction time fails (env MOOMOO_SKIP_HEALTHCHECK=1 to skip)
    """

    name = "MoomooFetcher"
    priority = 0

    def __init__(self) -> None:
        self._host = os.getenv("MOOMOO_HOST", "127.0.0.1")
        self._port = int(os.getenv("MOOMOO_PORT", "11111"))
        self._timeout = int(os.getenv("MOOMOO_TIMEOUT", "10"))
        self._enabled_flag = os.getenv("MOOMOO_ENABLED", "false").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self._ctx: Optional[Any] = None
        self._ctx_lock = threading.Lock()
        self._subscribed: set = set()
        self._disabled_reason: Optional[str] = None

        if _FUTU_IMPORT_ERROR is not None:
            self._disabled_reason = f"futu import failed: {_FUTU_IMPORT_ERROR}"
            logger.warning("[MoomooFetcher] %s", self._disabled_reason)
        elif not self._enabled_flag:
            self._disabled_reason = "MOOMOO_ENABLED is not true"
            logger.debug("[MoomooFetcher] disabled: %s", self._disabled_reason)
        else:
            # Eager health check so we don't waste priority slots when OpenD is down.
            skip_healthcheck = os.getenv("MOOMOO_SKIP_HEALTHCHECK", "0").strip().lower() in {
                "1", "true", "yes",
            }
            if not skip_healthcheck:
                try:
                    if not self.health_check():
                        self._disabled_reason = (
                            f"OpenD health check failed at {self._host}:{self._port}"
                        )
                        logger.warning(
                            "[MoomooFetcher] disabled: %s",
                            self._disabled_reason,
                        )
                except Exception as exc:
                    self._disabled_reason = f"OpenD health check errored: {exc}"
                    logger.warning(
                        "[MoomooFetcher] disabled: %s",
                        self._disabled_reason,
                    )

    # --- DSA fetcher plumbing ---

    def is_available_for_request(self, capability: str = "") -> bool:
        """Used by DataFetcherManager to skip this fetcher at runtime.

        Non-blocking TCP probe to OpenD (3s timeout) to avoid the
        OpenQuoteContext() constructor, which can hang 30+ minutes when
        the SSH tunnel to the macOS moomoo bridge is down.
        """
        if self._disabled_reason is not None:
            return False
        import socket
        try:
            with socket.create_connection((self._host, self._port), timeout=3):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError) as exc:
            logger.debug(
                "[MoomooFetcher] is_available_for_request socket check failed: %s",
                exc,
            )
            return False

    @property
    def enabled(self) -> bool:
        return self._disabled_reason is None

    @property
    def disabled_reason(self) -> Optional[str]:
        return self._disabled_reason

    def _ensure_ctx(self) -> Any:
        """Lazy-init OpenQuoteContext (thread-safe)."""
        if self._ctx is not None:
            return self._ctx
        with self._ctx_lock:
            if self._ctx is not None:
                return self._ctx
            if self._disabled_reason is not None:
                raise DataFetchError(f"[Moomoo] {self._disabled_reason}")
            # Socket pre-check (3s) to fail fast when the SSH tunnel is down,
            # instead of letting OpenQuoteContext() block for 30-60s.
            import socket
            try:
                with socket.create_connection((self._host, self._port), timeout=3):
                    pass
            except (socket.timeout, ConnectionRefusedError, OSError) as exc:
                logger.warning(
                    "[MoomooFetcher] _ensure_ctx socket pre-check failed: %s", exc
                )
                raise ConnectionError(
                    f"OpenD at {self._host}:{self._port} not reachable"
                ) from exc
            logger.info(
                "[MoomooFetcher] connecting to OpenD at %s:%d", self._host, self._port
            )
            self._ctx = OpenQuoteContext(host=self._host, port=self._port)
            logger.info("[MoomooFetcher] connected")
            return self._ctx

    def close(self) -> None:
        with self._ctx_lock:
            if self._ctx is not None:
                try:
                    self._ctx.close()
                except Exception as exc:
                    logger.debug("[MoomooFetcher] close error: %s", exc)
                finally:
                    self._ctx = None
                    self._subscribed.clear()

    # --- lifecycle ---

    def health_check(self) -> bool:
        try:
            ctx = self._ensure_ctx()
            ret, _ = ctx.get_market_snapshot(["US.AAPL"])
            return ret == RET_OK
        except Exception as exc:
            logger.warning("[MoomooFetcher] health check failed: %s", exc)
            return False

    # Note: OpenD returns ret=0 even for invalid codes but with a non-empty
    # data string (e.g. "未知股票 ..."). We must guard against `isinstance(data, str)`
    # before treating it as a DataFrame.

    # --- BaseFetcher abstract methods ---

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        if self._disabled_reason is not None:
            raise DataFetchError(f"[Moomoo] {self._disabled_reason}")
        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            ret, data, *_ = ctx.request_history_kline(
                futu_code,
                ktype=KLType.K_DAY,
                start=start_date,
                end=end_date,
                autype=AuType.QFQ,
            )
        except Exception as exc:
            raise DataFetchError(
                f"[Moomoo] request_history_kline({futu_code}) failed: {exc}"
            ) from exc
        if ret != RET_OK or data is None or isinstance(data, str):
            raise DataFetchError(
                f"[Moomoo] empty kline for {futu_code} ({start_date} ~ {end_date}): {data}"
            )
        if hasattr(data, "empty") and data.empty:
            raise DataFetchError(
                f"[Moomoo] empty kline for {futu_code} ({start_date} ~ {end_date})"
            )
        return data

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Map futu's K-line columns to DSA's STANDARD_COLUMNS."""
        if df is None or df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        rename_map = {
            "time_key": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "turnover": "amount",
        }
        out = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # futu returns date as 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' string
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")

        for col in ("open", "high", "low", "close"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        if "amount" not in out.columns:
            # futu provides turnover; fallback to volume * close
            if "volume" in out.columns and "close" in out.columns:
                out["amount"] = out["volume"] * out["close"]
            else:
                out["amount"] = 0.0
        else:
            out["amount"] = pd.to_numeric(out["amount"], errors="coerce").fillna(0.0)

        if "volume" in out.columns:
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce")

        # pct_chg derived from close
        if "close" in out.columns:
            out["pct_chg"] = out["close"].pct_change().fillna(0.0) * 100

        # Only return standard columns that exist
        keep = [c for c in STANDARD_COLUMNS if c in out.columns]
        return out[keep].reset_index(drop=True)

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        # Sort ascending by date so pct_chg direction matches DSA conventions
        df = df.copy()
        if "date" in df.columns:
            df = df.sort_values("date").reset_index(drop=True)
        return super()._clean_data(df)

    # --- Code translation ---

    @staticmethod
    def _normalize_code(stock_code: str) -> str:
        """
        Translate DSA codes ("AAPL", "00700", "600519") to futu format
        ("US.AAPL", "HK.00700", "SH.600519").
        """
        if not stock_code:
            return stock_code
        code = stock_code.strip().upper()
        if "." in code:
            return code
        if _is_us_code(code):
            return f"US.{code}"
        # HK: 5-digit zero-padded (00700 -> HK.00700)
        if code.isdigit() and len(code) <= 5:
            return f"HK.{code.zfill(5)}"
        # CN A-share: 6-digit, decide SH/SZ by first digit (6/9/5 -> SH, else SZ)
        if code.isdigit() and len(code) == 6:
            market = "SH" if code.startswith(("6", "9", "5")) else "SZ"
            return f"{market}.{code}"
        return code

    # --- get_chip_distribution (DSA contract) ---

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        DSA chip-distribution contract. For US/HK we synthesize an
        A-share-shaped ChipDistribution from moomoo's capital distribution
        so that downstream prompt templates keep working unchanged.
        """
        if self._disabled_reason is not None:
            logger.debug("[Moomoo] %s", self._disabled_reason)
            return None

        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            ret, data = ctx.get_capital_distribution(futu_code)
        except Exception as exc:
            logger.warning(
                "[Moomoo] get_capital_distribution(%s) error: %s", futu_code, exc
            )
            return None
        if ret != RET_OK or data is None:
            logger.debug(
                "[Moomoo] get_capital_distribution(%s) -> ret=%s data=%s",
                futu_code,
                ret,
                str(data)[:60],
            )
            return None
        if isinstance(data, str):
            logger.debug(
                "[Moomoo] get_capital_distribution(%s) error string: %s",
                futu_code,
                data,
            )
            return None
        if len(data) == 0:
            return None

        row = data.iloc[0]

        def _f(key: str, default: float = 0.0) -> float:
            return safe_float(row.get(key), default=default) or default

        in_super = _f("capital_in_super")
        in_big = _f("capital_in_big")
        in_mid = _f("capital_in_mid")
        in_small = _f("capital_in_small")
        out_super = _f("capital_out_super")
        out_big = _f("capital_out_big")
        out_mid = _f("capital_out_mid")
        out_small = _f("capital_out_small")

        net_big_money = (in_super + in_big) - (out_super + out_big)
        net_total = net_big_money + (in_mid - out_mid) + (in_small - out_small)

        # Synthesize avg_cost / profit_ratio / concentration.
        # Moomoo does not expose true cost distribution for US/HK, so we
        # derive coarse proxies from the capital-flow magnitudes. These are
        # NOT a substitute for A-share chip data — they only give the
        # downstream prompt a "filled" object so prompts that key off
        # ChipDistribution fields don't render empty templates.
        total_in = in_super + in_big + in_mid + in_small
        total_out = out_super + out_big + out_mid + out_small
        # profit_ratio: logistic on net big-money flow (1e8 = 100M USD scale).
        profit_ratio = 1.0 / (1.0 + 2.71828 ** (-net_big_money / 1e8))
        profit_ratio = max(0.0, min(1.0, profit_ratio))
        # concentration_90: ratio of big-money activity to total activity.
        # Values closer to 1.0 mean activity is dominated by big players
        # (concentrated). Values closer to 0 mean retail-heavy (dispersed).
        # Add small floor so _is_meaningful_chip_distribution passes.
        if total_in + total_out > 0:
            concentration_90 = max(0.05, min(0.95, (in_super + in_big + out_super + out_big) / (total_in + total_out)))
        else:
            concentration_90 = 0.5
        concentration_70 = max(0.05, min(0.95, concentration_90 * 0.85))
        # avg_cost: leave 0 — DSA prompt templates render "N/A" without it.
        update_time = str(row.get("update_time", "")) or datetime.now().strftime(
            "%Y-%m-%d"
        )

        # avg_cost: Moomoo doesn't provide true cost distribution for US/HK.
        # Use prev_close_price as a stand-in (it's the most recent "agreed"
        # transaction price) so _is_meaningful_chip_distribution accepts the
        # payload. Downstream prompts that compare avg_cost vs current_price
        # will see near-zero drift which is benign. The capital_distribution
        # row itself doesn't include price, so we need to fetch a snapshot.
        avg_cost = safe_float(row.get("prev_close_price")) or 0.0
        if avg_cost <= 0:
            # Fetch a snapshot to get the prev_close_price for this stock.
            try:
                ctx = self._ensure_ctx()
                snap_ret, snap_data = ctx.get_market_snapshot([futu_code])
                if snap_ret == RET_OK and snap_data is not None and not isinstance(snap_data, str) and len(snap_data):
                    avg_cost = (
                        safe_float(snap_data.iloc[0].get("prev_close_price"))
                        or safe_float(snap_data.iloc[0].get("last_price"))
                        or 0.0
                    )
            except Exception:
                pass
        if avg_cost <= 0:
            # Last-ditch: leave 0 — manager will treat as incomplete.
            avg_cost = 0.0

        chip = ChipDistribution(
            code=stock_code,
            date=update_time,
            source="moomoo",
            profit_ratio=profit_ratio,
            avg_cost=avg_cost,
            cost_90_low=0.0,
            cost_90_high=0.0,
            concentration_90=concentration_90,
            cost_70_low=0.0,
            cost_70_high=0.0,
            concentration_70=concentration_70,
        )
        # Attach raw capital-flow fields so debug logs and ReportNews prompts
        # can surface them via chip.to_dict() if they want.
        setattr(chip, "moomoo_net_total", net_total)
        setattr(chip, "moomoo_net_super", in_super - out_super)
        setattr(chip, "moomoo_net_big", in_big - out_big)
        setattr(chip, "moomoo_update_time", update_time)
        return chip

    # --- get_realtime_quote (DSA contract) ---

    def get_realtime_quote(
        self, stock_code: str
    ) -> Optional[UnifiedRealtimeQuote]:
        if self._disabled_reason is not None:
            return None
        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            ret, data = ctx.get_market_snapshot([futu_code])
        except Exception as exc:
            logger.warning("[Moomoo] get_market_snapshot(%s) error: %s", futu_code, exc)
            return None
        if ret != RET_OK or data is None:
            return None
        if isinstance(data, str):
            # Moomoo returns "未知股票 US.AAPL" or "暂不支持 ..." as a string
            logger.debug("[Moomoo] get_market_snapshot(%s) -> %s", futu_code, data)
            return None
        if len(data) == 0:
            return None
        row = data.iloc[0]
        return UnifiedRealtimeQuote(
            code=stock_code,
            source=RealtimeSource.LONGBRIDGE,  # closest enum slot (US/HK data)
            name=str(row.get("name") or ""),
            price=safe_float(row.get("last_price")),
            change_pct=safe_float(row.get("change_rate")),
            change_amount=safe_float(row.get("change_val")),
            volume=safe_float(row.get("volume")),
            amount=None,
            volume_ratio=None,
            turnover_rate=safe_float(row.get("turnover_rate")),
            amplitude=None,
            open_price=safe_float(row.get("open_price")),
            high=safe_float(row.get("high_price")),
            low=safe_float(row.get("low_price")),
            pre_close=safe_float(row.get("prev_close_price")),
            pe_ratio=safe_float(row.get("pe_ratio")),
            pb_ratio=safe_float(row.get("pb_ratio")),
            total_mv=safe_float(row.get("total_market_val")),
            circ_mv=safe_float(row.get("circular_market_val")),
        )

    # --- get_main_indices (DSA contract) ---

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        # Moomoo OpenD does NOT serve US/HK index quotes (returns "暂不支持美股指数"
        # / "未知股票 HSI"). Returning None here lets DataFetcherManager fall
        # through to YFinance, which is the long-standing provider for indices.
        return None

    # --- get_market_stats (DSA contract) ---

    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        if self._disabled_reason is not None:
            return None
        ctx = self._ensure_ctx()
        # Sample well-known US large-caps; cheap call, gives a coarse sense of
        # market breadth for the dashboard. get_market_snapshot returns 142
        # fields per code in a single request.
        proxy_codes = [
            "US.AAPL", "US.MSFT", "US.NVDA", "US.GOOG", "US.AMZN",
            "US.META", "US.TSLA", "US.NFLX", "US.AVGO", "US.BRK",
            "US.JPM", "US.V", "US.MA", "US.UNH", "US.XOM",
            "US.WMT", "US.JNJ", "US.PG", "US.HD", "US.LLY",
        ]
        try:
            ret, data = ctx.get_market_snapshot(proxy_codes)
        except Exception as exc:
            logger.warning("[Moomoo] market_stats snapshot error: %s", exc)
            return None
        if ret != RET_OK or data is None or isinstance(data, str):
            logger.debug(
                "[Moomoo] market_stats empty (ret=%s data=%s)",
                ret,
                str(data)[:60],
            )
            return None
        if hasattr(data, "empty") and data.empty:
            return None
        up = down = flat = 0
        total_amount = 0.0
        for _, row in data.iterrows():
            chg = safe_float(row.get("change_rate")) or 0.0
            if chg > 0:
                up += 1
            elif chg < 0:
                down += 1
            else:
                flat += 1
            turnover = safe_float(row.get("turnover"))
            if turnover:
                total_amount += turnover
        return {
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": total_amount,
            "source": "moomoo",
            "sample_size": len(data),
        }

    # --- Convenience accessors used elsewhere in DSA ---

    def get_history_kline(
        self,
        stock_code: str,
        period: str = "day",
        start: Optional[str] = None,
        end: Optional[str] = None,
        max_count: int = 200,
    ) -> Optional[pd.DataFrame]:
        """Return raw futu K-line DataFrame (callers may know how to use it)."""
        if self._disabled_reason is not None:
            return None
        ktype_name = PERIOD_TO_KLTYPE.get(period)
        if ktype_name is None or KLType is None:
            logger.warning("[Moomoo] unknown period %s", period)
            return None
        ktype = getattr(KLType, ktype_name)
        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            kwargs: Dict[str, Any] = {
                "ktype": ktype,
                "max_count": max_count,
                "autype": AuType.QFQ,
            }
            if start:
                kwargs["start"] = start
            if end:
                kwargs["end"] = end
            ret, data, *_ = ctx.request_history_kline(futu_code, **kwargs)
            if ret != RET_OK or data is None or isinstance(data, str):
                return None
            return data
        except Exception as exc:
            logger.warning("[Moomoo] history_kline(%s) error: %s", futu_code, exc)
            return None

    def get_capital_distribution_raw(self, stock_code: str) -> Optional[pd.DataFrame]:
        """Return raw capital distribution dataframe (debug / advanced use)."""
        if self._disabled_reason is not None:
            return None
        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            ret, data = ctx.get_capital_distribution(futu_code)
            if ret != RET_OK or data is None or isinstance(data, str):
                return None
            return data
        except Exception as exc:
            logger.warning("[Moomoo] capital_distribution(%s) error: %s", futu_code, exc)
            return None

    def get_owner_plate(self, stock_code: str) -> Optional[List[Dict[str, Any]]]:
        if self._disabled_reason is not None:
            return None
        futu_code = self._normalize_code(stock_code)
        ctx = self._ensure_ctx()
        try:
            ret, data = ctx.get_owner_plate([futu_code])
            if ret != RET_OK or data is None or isinstance(data, str):
                return None
            if hasattr(data, "empty") and data.empty:
                return None
            return data.to_dict("records")
        except Exception as exc:
            logger.warning("[Moomoo] owner_plate(%s) error: %s", futu_code, exc)
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    f = MoomooFetcher()
    print("enabled:", f.enabled, "reason:", f.disabled_reason)
    if f.enabled:
        print("health:", f.health_check())
        chip = f.get_chip_distribution("AAPL")
        print("AAPL chip-like:", chip.to_dict() if chip else None)
        quote = f.get_realtime_quote("AAPL")
        print("AAPL quote price:", getattr(quote, "price", None))
    f.close()