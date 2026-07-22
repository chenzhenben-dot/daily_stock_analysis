# -*- coding: utf-8 -*-
"""Structured Market Light snapshot schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MarketRegion = Literal["cn", "hk", "us", "jp", "kr"]
MarketLightStatus = Literal["green", "yellow", "red"]
MarketLightDataQuality = Literal["ok", "partial", "unavailable"]
MARKET_LIGHT_REGIONS = frozenset(("cn", "hk", "us"))


class MarketLightDimension(BaseModel):
    """A single Market Light scoring dimension."""

    score: int = Field(ge=0, le=100)
    available: bool


class MarketLightDimensions(BaseModel):
    """Canonical Market Light dimension scores.

    The ``limit`` dimension is only populated for CN (A-share style daily
    limit-up / limit-down statistics). US / HK / JP / KR do not have a
    comparable market-wide limit metric, so the field is optional and the
    score is omitted from the snapshot.
    """

    breadth: MarketLightDimension
    index: MarketLightDimension
    limit: MarketLightDimension | None = None


class MarketLightSnapshot(BaseModel):
    """Structured Market Light snapshot persisted and consumed by alerts."""

    region: MarketRegion
    trade_date: str
    status: MarketLightStatus
    score: int = Field(ge=0, le=100)
    label: str
    temperature_label: str
    reasons: list[str]
    guidance: str
    dimensions: MarketLightDimensions
    data_quality: MarketLightDataQuality
