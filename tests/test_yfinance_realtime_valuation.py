# -*- coding: utf-8 -*-
"""Regression tests for yfinance realtime valuation fields."""

from types import SimpleNamespace
from unittest.mock import patch

from data_provider.yfinance_fetcher import YfinanceFetcher


def test_us_realtime_quote_includes_pe_and_pb_from_ticker_info() -> None:
    ticker = SimpleNamespace(
        fast_info=SimpleNamespace(
            lastPrice=210.0,
            previousClose=200.0,
            open=202.0,
            dayHigh=212.0,
            dayLow=199.0,
            lastVolume=123456,
            marketCap=3_000_000_000_000,
        ),
        info={
            "shortName": "Apple Inc.",
            "currency": "USD",
            "trailingPE": "31.25",
            "priceToBook": 42.5,
        },
    )

    with patch("data_provider.yfinance_fetcher.yf.Ticker", return_value=ticker):
        quote = YfinanceFetcher().get_realtime_quote("AAPL")

    assert quote is not None
    assert quote.pe_ratio == 31.25
    assert quote.pb_ratio == 42.5
    assert quote.missing_fields == ["amount"]
