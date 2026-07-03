# -*- coding: utf-8 -*-
"""
新闻情感分类 (利好/利空/中性)

批量对 ``news_intel`` 表里的新闻打 sentiment 标签,用于在 ReportNews
卡片里显示 利好/利空/中性 徽标。

核心流程:
1. 取出某 query_id 下所有未分类的新闻 (sentiment IS NULL)
2. 一次 LLM 调用批量分类, 复用 MiniMax-M3 (隐式 prompt cache)
3. 写回 DB, 永久缓存, 同 query_id 不重复调用

失败降级: 任何异常都会被调用方 catch, sentiment 留空, 前端按 neutral 渲染。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.analyzer import GeminiAnalyzer
from src.config import get_config
from src.storage import NewsIntel

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a financial news sentiment classifier. Classify each item as exactly one of: positive, negative, neutral.

Rules:
- "positive": material upside catalyst (earnings beat, upgrade, contract win, guidance raise, buyback, accretive M&A, major new product).
- "negative": material downside catalyst (miss, downgrade, lawsuit, guidance cut, regulatory action, fraud, major layoff).
- "neutral": routine coverage, opinion, macro commentary with no direct ticker impact.

Return a JSON array only. No prose, no markdown, no explanation."""


_ALLOWED_SENTIMENTS = {"positive", "negative", "neutral"}
_MAX_BATCH_SIZE = 30
_SNIPPET_MAX_CHARS = 400
_REASON_MAX_CHARS = 480


def _build_user_payload(items: List[NewsIntel]) -> str:
    payload = []
    for item in items:
        title = (item.title or "").strip()
        snippet = (item.snippet or "").strip()[:_SNIPPET_MAX_CHARS]
        payload.append({
            "id": int(item.id),
            "title": title,
            "snippet": snippet,
        })
    body = json.dumps(payload, ensure_ascii=False)
    return (
        "Classify each news item. Return JSON array with this exact shape:\n"
        '[{"id": <int>, "sentiment": "positive|negative|neutral", '
        '"confidence": <0-1>, "reason": "<=15 words in the original language of the title>"}]\n\n'
        f"News items:\n{body}"
    )


def classify_news_sentiment(
    items: List[NewsIntel],
    *,
    analyzer: Optional[GeminiAnalyzer] = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Classify a batch of news items via the configured LLM.

    Returns a list of dicts ``{id, sentiment, confidence, reason}``.
    Raises on JSON parse failure or transport failure — caller decides
    how to fall back.
    """
    if not items:
        return []

    batch = list(items)[:_MAX_BATCH_SIZE]
    user_prompt = _build_user_payload(batch)

    if analyzer is None:
        config = get_config()
        analyzer = GeminiAnalyzer(config=config)

    max_tokens = min(2000, 80 * len(batch) + 200)
    raw_text, _model, _usage = analyzer._call_litellm(
        user_prompt,
        {"temperature": 0.0, "max_tokens": max_tokens},
        system_prompt=SYSTEM_PROMPT,
    )

    # _call_litellm returns plain text; analyzer's helper is a method on the
    # GeminiAnalyzer class. Use a small inline parse instead.
    raw_text = (raw_text or "").strip()
    obj = _parse_json_response(raw_text)
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        obj = obj["items"]
    if not isinstance(obj, list):
        raise ValueError("sentiment classifier returned non-list payload")
    return obj


def _parse_json_response(text: str) -> Any:
    """Robust JSON parse: strip markdown fences, attempt json.loads, fall back
    to the first balanced array/object in the text."""
    import re

    if not text:
        raise ValueError("empty classifier response")

    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    candidate = fenced.group(1) if fenced else text

    try:
        return json.loads(candidate)
    except Exception:
        pass

    # Try to extract the first balanced array
    array_match = re.search(r"\[[\s\S]+\]", candidate)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except Exception:
            pass

    # Try to extract the first balanced object
    obj_match = re.search(r"\{[\s\S]+\}", candidate)
    if obj_match:
        try:
            return json.loads(obj_match.group(0))
        except Exception:
            pass

    raise ValueError(f"unable to parse JSON from classifier response: {text[:200]}")


def normalize_sentiment_rows(
    rows: Iterable[Dict[str, Any]],
    by_id: Dict[int, NewsIntel],
) -> List[Tuple[int, str, float, str]]:
    """Normalize raw classifier output into a list of DB-ready tuples.

    - Unknown sentiment labels fall back to ``neutral``.
    - ``confidence`` is clamped to ``[0.0, 1.0]``.
    - ``reason`` is truncated to ``_REASON_MAX_CHARS`` characters.
    - Rows whose ``id`` is not in ``by_id`` are dropped (defends against
      prompt injection attempting to write to other rows).
    """
    out: List[Tuple[int, str, float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            news_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if news_id not in by_id:
            continue

        sentiment = str(row.get("sentiment") or "").lower().strip()
        if sentiment not in _ALLOWED_SENTIMENTS:
            sentiment = "neutral"

        try:
            confidence = float(row.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        reason = str(row.get("reason") or "").strip()[:_REASON_MAX_CHARS]

        out.append((news_id, sentiment, confidence, reason))
    return out
