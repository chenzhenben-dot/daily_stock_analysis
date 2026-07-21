#!/usr/bin/env python3
import datetime
import json
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DSA_ENV_PATH = "/opt/dsa/.env"

# === SEC XBRL deterministic extractor (pure functions, no LLM) ===
#
# These functions are called only from fetch_sec_recent_filings() to pre-compute
# structured metrics from the SEC companyfacts JSON. The output is stored at
# stock_data["sec_financials"] and is consulted by normalize_dashboard_data()
# so we never rely on the LLM for revenue, margin, EPS, cash-flow or balance
# sheet figures that SEC has already disclosed.
#
# All implementations are Python 3.6 compatible (no f-strings with `=`, no PEP
# 604 unions, no walrus operator, no dataclasses).

SEC_FINANCIAL_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "eps_basic": ("EarningsPerShareBasic",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "lt_debt_current": ("LongTermDebtCurrent",),
    "lt_debt_noncurrent": ("LongTermDebtNoncurrent",),
}
SEC_FORMS = ("10-K", "10-Q", "20-F", "6-K")


def _parse_iso_date(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return datetime.datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _duration_days(fact):
    # Accept either raw SEC keys ("start", "end") or normalised ones
    # ("period_start", "period_end") — the override path consumes both.
    s = _parse_iso_date(fact.get("start") or fact.get("period_start"))
    e = _parse_iso_date(fact.get("end") or fact.get("period_end"))
    if not s or not e:
        return None
    return (e - s).days


def _is_duration(fact):
    return bool(fact.get("start")) and bool(fact.get("end"))


def _dedupe_facts(entries):
    """Drop facts with the same (val, end, start) tuple — same filing often
    re-states a number across the same frame; we only need one copy."""
    seen = set()
    out = []
    for entry in entries:
        key = (
            entry.get("val"),
            entry.get("end"),
            entry.get("start"),
            entry.get("accn") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _filter_facts(entries, form=None, fp=None):
    """Apply SEC eligibility filters and optional form/fp matchers."""
    out = []
    for entry in entries:
        if entry.get("form") not in SEC_FORMS:
            continue
        if form is not None and entry.get("form") != form:
            continue
        if fp is not None and entry.get("fp") != fp:
            continue
        out.append(entry)
    return out


def select_latest_duration_fact(entries, form=None, fp=None,
                                min_days=None, max_days=None):
    """Pick the latest duration fact that matches the requested form/fp.

    ``min_days`` / ``max_days`` constrain the duration window so a single
    quarter (~89 days) is preferred over YTD (~270 days) when callers ask for
    a quarter. If no entry sits inside the window the function widens to the
    ``max_days`` cap and finally falls back to the most recent fact, so
    callers always get something rather than None unless they say so via the
    ``require_window`` flag in :func:`extract_sec_financial_metrics`.
    """
    candidates = [e for e in entries if _is_duration(e)]
    if form is not None:
        candidates = [e for e in candidates if e.get("form") == form]
    if fp is not None:
        candidates = [e for e in candidates if e.get("fp") == fp]
    if not candidates:
        return None
    candidates = _dedupe_facts(candidates)
    if min_days is not None or max_days is not None:
        in_window = []
        for entry in candidates:
            days = _duration_days(entry)
            if days is None:
                continue
            if min_days is not None and days < min_days:
                continue
            if max_days is not None and days > max_days:
                continue
            in_window.append(entry)
        if in_window:
            candidates = in_window
    candidates.sort(key=lambda e: (e.get("end") or "", e.get("filed") or ""), reverse=True)
    return candidates[0] if candidates else None


def select_instant_fact(entries, form=None, fp=None):
    candidates = [e for e in entries if not _is_duration(e)]
    if form is not None:
        candidates = [e for e in candidates if e.get("form") == form]
    if fp is not None:
        candidates = [e for e in candidates if e.get("fp") == fp]
    if not candidates:
        return None
    candidates = _dedupe_facts(candidates)
    candidates.sort(key=lambda e: (e.get("end") or "", e.get("filed") or ""), reverse=True)
    return candidates[0] if candidates else None


def select_comparable_fact(entries, anchor, periods_back=1, fp=None):
    """Return the same-fp fact from ``anchor.fy - periods_back``.

    Used to fetch YoY comparables for revenue, gross profit, etc. without
    accidentally picking the prior year-end filing's full-year number when we
    actually want the same-quarter value from a year ago.
    """
    if not anchor:
        return None
    anchor_fy = anchor.get("fy")
    if anchor_fy is None:
        return None
    target_fy = anchor_fy - periods_back
    target_fp = fp or anchor.get("fp") or "FY"
    candidates = [e for e in entries
                  if _is_duration(e)
                  and e.get("fy") == target_fy
                  and e.get("fp") == target_fp
                  and e.get("form") in SEC_FORMS]
    if not candidates:
        return None
    anchor_days = _duration_days(anchor)
    if anchor_days is not None and anchor_days < 200:
        # Quarter-level anchor; prefer same-shape fact
        ideal = [e for e in candidates
                 if _duration_days(e) is not None
                 and abs(_duration_days(e) - anchor_days) <= 14]
        if ideal:
            candidates = ideal
    candidates = _dedupe_facts(candidates)
    candidates.sort(key=lambda e: (e.get("end") or "", e.get("filed") or ""), reverse=True)
    return candidates[0] if candidates else None


def format_currency(value, scale=None):
    """Compact currency formatter used for short display fields.

    Returns None when value is missing/invalid — callers fall back to a
    missing-state label rather than printing a raw number.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if scale is None:
        scale = "auto"
    abs_n = abs(number)
    if scale == "auto":
        if abs_n >= 1e12:
            return "${:.2f}T".format(number / 1e12)
        if abs_n >= 1e9:
            return "${:.2f}B".format(number / 1e9)
        if abs_n >= 1e6:
            return "${:.2f}M".format(number / 1e6)
        if abs_n >= 1e3:
            return "${:.2f}K".format(number / 1e3)
        return "${:.2f}".format(number)
    return "${:,.2f}".format(number)


def safe_ratio(numerator, denominator, scale=100.0, as_percent=True):
    """Divide without raising on zero / non-numeric values."""
    if numerator is None or denominator is None:
        return None
    try:
        n = float(numerator)
        d = float(denominator)
    except (TypeError, ValueError):
        return None
    if d == 0:
        return None
    ratio = (n / d) * scale
    if as_percent:
        return ratio
    return ratio / 100.0


def _entries_for_tag(companyfacts, taxonomy, tag):
    block = ((companyfacts.get("facts") or {}).get(taxonomy) or {}).get(tag)
    if not block:
        return []
    entries = []
    for unit_rows in (block.get("units") or {}).values():
        if isinstance(unit_rows, list):
            entries.extend(unit_rows)
    return entries


def _pick_tag(facts_payload, tag_tuple):
    """Return the first taxonomy that has any eligible tag entries."""
    for taxonomy in ("us-gaap", "ifrs-full", "dei"):
        for tag in tag_tuple:
            entries = _entries_for_tag(facts_payload, taxonomy, tag)
            entries = [e for e in entries if e.get("form") in SEC_FORMS]
            if entries:
                return taxonomy, tag, entries
    return None, None, []


def _normalize_fact(entries, anchor_entry):
    """Build a compact dict summarizing the fact and its source attribution."""
    latest = entries[0]
    duration = _duration_days(latest)
    return {
        "tag": latest.get("tag") or "",
        "form": latest.get("form"),
        "fp": latest.get("fp"),
        "fy": latest.get("fy"),
        "frame": latest.get("frame"),
        "val": latest.get("val"),
        "unit": latest.get("unit") or "USD",
        "period_start": latest.get("start"),
        "period_end": latest.get("end"),
        "filed": latest.get("filed"),
        "accn": latest.get("accn"),
        "duration_days": duration,
        "scope": ("q" if duration is not None and duration <= 100
                  else "ytd" if duration is not None and duration <= 200
                  else "fy"),
        "all_entries_count": len(entries),
        "anchor": bool(anchor_entry),
    }


def extract_sec_financial_metrics(companyfacts):
    """Top-level SEC extractor.

    Returns a compact dict ready to drop into ``stock_data["sec_financials"]``.
    The LLM never sees this structure — it is consumed by
    :func:`normalize_dashboard_data` to deterministically fill the financial
    fields. Output schema::

        {
          "cik": "0002023554",
          "entity_name": "...",
          "taxonomy": "us-gaap",
          "as_of_filed": "2026-05-01",       # latest filing
          "latest_quarter_label": "FY2026 Q3",
          "latest_quarter_end": "2026-04-03",
          "metrics": {
            "revenue": {
              "latest_q":   {tag, form, fp, fy, val, period_start,
                             period_end, filed, duration_days, scope},
              "ytd":        {...},
              "fy":         {...},
              "yoy_q":      {...},
              "ytd_yoy":    {...},
              "qoq":        {...},   # vs prior quarter
              "q_yoy_pct":  28.4,
              "q_qoq_pct":  12.1,
            },
            ...
          },
          "balance_sheet": [
            {"label": "Total Assets", "value": 17.075e9,
             "period_end": "...", "filed": "...", "form": "10-Q",
             "yoy_change_pct": 31.5, "source_tag": "Assets"},
            ...
          ],
          "tags_used": [...],  # the actual us-gaap tag picked
        }
    """
    if not isinstance(companyfacts, dict):
        return {"available": False, "reason": "no companyfacts payload"}
    out = {
        "available": True,
        "cik": (companyfacts.get("cik") or "") and str(companyfacts.get("cik")),
        "entity_name": companyfacts.get("entityName") or "",
        "taxonomy": "us-gaap",
        "as_of_filed": None,
        "latest_quarter_label": None,
        "latest_quarter_end": None,
        "metrics": {},
        "balance_sheet": [],
        "tags_used": [],
    }
    facts_block = companyfacts.get("facts") or {}
    if not facts_block:
        return {"available": False, "reason": "empty facts block"}

    # 1. Pull every tag we care about. Iterate us-gaap; ifrs-full only as
    #    a fallback for non-US issuers.
    metrics = out["metrics"]
    for metric_name, tag_tuple in SEC_FINANCIAL_TAGS.items():
        for taxonomy in ("us-gaap", "ifrs-full"):
            tag_entries = {}
            picked = False
            for tag in tag_tuple:
                entries = _entries_for_tag(companyfacts, taxonomy, tag)
                entries = [e for e in entries if e.get("form") in SEC_FORMS]
                if entries:
                    tag_entries[tag] = entries
                    out["tags_used"].append("{}.{}".format(taxonomy, tag))
                    picked = True
                    break  # one tag per metric
            if not picked:
                continue
            tag = list(tag_entries.keys())[0]
            entries = _dedupe_facts(tag_entries[tag])

            latest_q = select_latest_duration_fact(
                entries, form="10-Q", min_days=70, max_days=100)
            ytd = select_latest_duration_fact(
                entries, form="10-Q", min_days=180, max_days=300)
            fy = select_latest_duration_fact(
                entries, form="10-K", min_days=340, max_days=380)
            if latest_q is None and ytd is not None and _duration_days(ytd) and _duration_days(ytd) < 200:
                latest_q = ytd
            yoy_q = select_comparable_fact(entries, latest_q or ytd or fy,
                                           periods_back=1, fp=(latest_q or {}).get("fp"))
            ytd_yoy = select_comparable_fact(entries, ytd,
                                              periods_back=1, fp=(ytd or {}).get("fp"))
            qoq = None
            if latest_q is not None:
                qoq = select_comparable_fact(entries, latest_q,
                                             periods_back=1, fp=(latest_q or {}).get("fp"))
                # qoq needs period_back=1 quarter, not 1 year. We approximate:
                # find the immediately prior 10-Q of same fp structure but fy-1
                # would be wrong; we'd need fy same, fp previous. Skip if not
                # deterministically derivable.

            metric_block = {
                "tag": tag,
                "taxonomy": taxonomy,
                "latest_q": _normalize_fact([latest_q], latest_q) if latest_q else None,
                "ytd": _normalize_fact([ytd], ytd) if ytd else None,
                "fy": _normalize_fact([fy], fy) if fy else None,
                "yoy_q": _normalize_fact([yoy_q], yoy_q) if yoy_q else None,
                "ytd_yoy": _normalize_fact([ytd_yoy], ytd_yoy) if ytd_yoy else None,
            }
            q_val = (metric_block["latest_q"] or {}).get("val")
            q_prior = (metric_block["yoy_q"] or {}).get("val")
            metric_block["q_yoy_pct"] = safe_ratio(
                (q_val - q_prior) if (q_val is not None and q_prior is not None) else None,
                q_prior) if q_val is not None and q_prior is not None else None
            ytd_v = (metric_block["ytd"] or {}).get("val")
            ytd_prior = (metric_block["ytd_yoy"] or {}).get("val")
            metric_block["ytd_yoy_pct"] = safe_ratio(
                (ytd_v - ytd_prior) if (ytd_v is not None and ytd_prior is not None) else None,
                ytd_prior) if ytd_v is not None and ytd_prior is not None else None
            metrics[metric_name] = metric_block

    # 2. Most-recent filing date seen anywhere
    for entries in [
        e for v in metrics.values() if isinstance(v, dict)
        for e in ((v.get("latest_q") or {}), (v.get("ytd") or {}), (v.get("fy") or {}))
        if e
    ]:
        filed = entries.get("filed")
        if filed and (out["as_of_filed"] is None or filed > out["as_of_filed"]):
            out["as_of_filed"] = filed

    # 3. Latest quarter label/end — use revenue or net income latest_q
    for key in ("revenue", "operating_income", "net_income"):
        m = metrics.get(key) or {}
        latest = m.get("latest_q") or {}
        if latest and latest.get("period_end"):
            label = "{}{}".format(
                "FY" + str(latest["fy"]) if latest.get("fy") else "FY",
                latest.get("fp") or "",
            )
            out["latest_quarter_label"] = label
            out["latest_quarter_end"] = latest["period_end"]
            break

    # 4. Balance sheet snapshot: pull latest 10-Q inst values for assets, etc.
    bs_rows = []
    bs_items = (
        ("assets", "Total Assets"),
        ("cash", "Cash & Equivalents"),
        ("liabilities", "Total Liabilities"),
        ("lt_debt_current", "Long-Term Debt (current)"),
        ("lt_debt_noncurrent", "Long-Term Debt (non-current)"),
    )
    for metric_key, label in bs_items:
        m = metrics.get(metric_key)
        if not m:
            continue
        entries = []
        tag = m.get("tag")
        for taxonomy in ("us-gaap", "ifrs-full"):
            entries = _entries_for_tag(companyfacts, taxonomy, tag)
            entries = [e for e in entries if e.get("form") in SEC_FORMS]
            if entries:
                break
        if not entries:
            continue
        instant = select_instant_fact(entries, form="10-Q")
        if instant is None:
            instant = select_instant_fact(entries)
        if instant is None:
            continue
        # Prior-period comparable: tolerate a wide window because the SEC
        # data may not have an exact same-day snapshot one year ago. We pick
        # the closest entry whose end date is between 270 and 540 days
        # before the anchor; that covers FY ends and prior 10-Q snapshots.
        prior = None
        anchor_date = _parse_iso_date(instant.get("end"))
        if anchor_date:
            candidates = []
            for entry in entries:
                d = _parse_iso_date(entry.get("end"))
                if not d:
                    continue
                delta = (anchor_date - d).days
                if 270 <= delta <= 540:
                    candidates.append((delta, entry))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                prior = candidates[0][1]
        bs_rows.append({
            "label": label,
            "tag": tag,
            "value": instant.get("val"),
            "period_end": instant.get("end"),
            "filed": instant.get("filed"),
            "form": instant.get("form"),
            "yoy_value": prior.get("val") if prior else None,
            "yoy_change_pct": safe_ratio(
                (instant.get("val") - prior.get("val"))
                if (instant.get("val") is not None and prior and prior.get("val") is not None)
                else None,
                prior.get("val") if prior else None,
            ),
        })
    out["balance_sheet"] = bs_rows
    return out
DASH_DIR = "/opt/er-dashboards"
LOCAL_SKILL_DIR = Path.home() / ".claude/skills/equity-research"
SERVER_SKILL_DIR = Path("/opt/er-dashboard/equity-research")
SKILL_DIR = SERVER_SKILL_DIR if (SERVER_SKILL_DIR / "SKILL.md").exists() else LOCAL_SKILL_DIR
SKILL_PATH = SKILL_DIR / "SKILL.md"
TEMPLATE_PATH = SKILL_DIR / "references/dashboard-template.html"
GENERATOR_PATH = SKILL_DIR / "references/dashboard-generator.py"

LIST_FIELDS = {"monitoring_metrics", "product_milestones", "valuation_assumptions", "invalidation_conditions", "sell_conditions", "data_conflicts", "data_sources"}
ROW_FIELDS = {"latest_quarter_rows", "fy_comparison_rows", "segment_rows", "guidance_rows", "valuation_rows", "balance_sheet_rows", "comp_financial_rows", "customer_rows", "catalyst_rows", "business_rows", "product_rows", "chain_rows"}
ROW_SCHEMAS = {
    "latest_quarter_rows": ["指标", "上年同期", "本季度", "同比", "vs预期", "评价"],
    "fy_comparison_rows": ["指标", "2025", "2024", "YoY"],
    "segment_rows": ["业务", "收入", "占比", "YoY", "Net Income", "战略作用"],
    "guidance_rows": ["指标", "指引", "YoY", "关键假设"],
    "valuation_rows": ["指标", "当前", "5y中位数", "评价"],
    "balance_sheet_rows": ["项目", "金额", "YoY变化", "解读"],
    "business_rows": ["业务/分部", "收入", "占比", "同比", "环比", "业务意义"],
    "product_rows": ["产品", "是什么", "客户为什么付钱", "成功看什么"],
    "chain_rows": ["上游采购", "→", "公司业务", "→", "下游客户"],
    "comp_financial_rows": ["公司", "相关业务", "收入", "增速", "毛利率", "EV/Sales", "备注"],
    "customer_rows": ["客户", "协议", "时间", "业务", "验证状态"],
    "catalyst_rows": ["类别", "事件", "时间", "维度"],
}
CLASS_FIELDS = {"conclusion_class", "price_change_class", "ytd_class", "revenue_change_class", "eps_change_class", "business_cycle_class", "price_cycle_class", "risk_self_class", "risk_substitute_class", "risk_geo_class", "risk_cycle_class", "verify_paid_class", "verify_repeat_class", "verify_production_class", "verify_concentration_class", "verify_source_class"}
UNKNOWN_DISPLAY = "未披露 / 待验证"
MISSING_NOT_DISCLOSED = "公司未单独披露"
MISSING_SOURCE_UNAVAILABLE = "数据源暂不可用"
MISSING_INSUFFICIENT_HISTORY = "历史不足"
MISSING_NOT_APPLICABLE = "不适用"
MISSING_TO_CROSS_VERIFY = "待交叉验证"
PROHIBITED_ADVICE_TERMS = (
    "目标价", "目标位", "买入价", "买入点", "入场价", "止损价", "止损位", "止盈价", "止盈位",
    "建议仓位", "仓位建议", "仓位控制", "加仓建议", "减仓建议", "position size", "target price",
    "entry price", "stop loss", "take profit",
)
SHORT_DISPLAY_FIELDS = {
    "current_price": "number", "price_change": "number", "price_change_pct": "percent",
    "market_cap": "currency", "enterprise_value": "currency", "net_debt": "currency",
    "week52_high": "number", "week52_low": "number", "ytd_return": "percent",
    "forward_pe": "multiple", "pe_median": "multiple", "ev_sales": "multiple",
    "forward_ev_sales": "multiple", "core_revenue_growth": "percent",
    "core_gross_margin": "percent", "margin_change": "number", "fcf_ttm": "currency",
    "fcf_yield": "percent",
}

FULL_RESEARCH_FIELD_GROUPS = [
    ("公司概览与投资问题", [
        "TICKER", "company_name", "exchange", "industry", "current_date", "analysis_timestamp",
        "phase_1_intent", "phase_1_horizon", "phase_1_security_type", "phase_1_core_question",
        "current_price", "price_change", "price_change_pct", "price_change_symbol", "price_change_class",
        "market_cap", "enterprise_value", "net_debt", "week52_high", "week52_low", "ytd_return", "ytd_class",
        "company_definition", "price_context",
    ]),
    ("最新财务、指引与估值", [
        "forward_pe", "pe_median", "ev_sales", "forward_ev_sales", "latest_quarter", "latest_revenue",
        "revenue_change", "revenue_change_class", "latest_eps", "eps_change", "eps_change_class",
        "core_revenue_growth", "core_gross_margin", "margin_change", "fcf_ttm", "fcf_yield",
        "latest_quarter_rows", "fy_comparison_rows", "segment_rows", "guidance_rows", "valuation_rows",
        "balance_sheet_rows",
    ]),
    ("业务、产品与产业链", [
        "business_quarter_label", "business_rows", "business_analogies", "business_summary",
        "product_rows", "product_analogy_box", "industry_chain_classification", "chain_overview", "chain_rows",
        "profit_type", "risk_self", "risk_self_class", "risk_substitute", "risk_substitute_class",
        "risk_geo", "risk_geo_class", "risk_cycle", "risk_cycle_class",
    ]),
    ("竞争格局与客户验证", [
        "comp_direct", "comp_indirect", "comp_substitute", "comp_insourcing", "comp_financial_rows",
        "product_difference", "winner_price", "reason_price", "winner_reliability", "reason_reliability",
        "winner_performance", "reason_performance", "winner_delivery", "reason_delivery", "customer_rows",
        "verify_paid", "verify_paid_class", "verify_repeat", "verify_repeat_class", "verify_production",
        "verify_production_class", "verify_concentration", "verify_concentration_class", "verify_source",
        "verify_source_class", "customer_risk",
    ]),
    ("周期、催化剂、行动与监控", [
        "business_cycle", "business_cycle_class", "business_cycle_desc", "price_cycle", "price_cycle_class",
        "price_cycle_desc", "catalyst_rows", "cycle_key_judgment", "next_earnings_date", "current_guidance",
        "monitoring_metrics", "product_milestones", "valuation_assumptions", "invalidation_conditions",
        "sell_conditions", "data_conflicts", "data_sources",
        "conclusion_class", "one_liner", "investment_thesis", "price_implication",
    ]),
]


def split_field_batches(fields, max_weight=12):
    """Split ER fields by expected output size, not only field count."""
    batches = []
    current = []
    current_weight = 0
    for field in fields:
        weight = 5 if field in ROW_FIELDS else 2 if field in LIST_FIELDS else 1
        if current and current_weight + weight > max_weight:
            batches.append(current)
            current = []
            current_weight = 0
        current.append(field)
        current_weight += weight
    if current:
        batches.append(current)
    return batches


# === SKILL.md 100% Compliance Constants ===

REQUIRED_FIELDS = {
    "phase_1_intent": "observe | buy | hold | wait | try | add | reduce | avoid",
    "phase_1_horizon": "short_term | mid_term | long_term",
    "phase_1_security_type": "common_stock | preferred | etf | reit | bond | other",
    "phase_1_core_question": "用户要求 ER 深度分析",
    "phase_2_1_definition.what": "公司卖什么、客户是谁、行业归属",
    "phase_2_1_definition.industry": "sub-industry + sector",
    "phase_2_1_definition.growth_logic": "投资人买这个增长逻辑",
    "phase_2_2_business.segments": "list of segments with name/revenue/share_pct/yoy/investment_meaning",
    "phase_2_2_business.summary": "business structure summary",
    "phase_2_2_business.primary_engine": "主增长引擎",
    "phase_2_2_business.stable_cash_cow": "稳定现金牛",
    "phase_2_2_business.future_option": "未来期权",
    "phase_2_3_products.products": "list of products with name/what/why_pay/success_metric",
    "phase_2_4_completeness.core_revenue_products": "core revenue products covered",
    "phase_2_4_completeness.growth_products": "growth products covered",
    "phase_2_4_completeness.future_options": "future options covered",
    "phase_2_4_completeness.declining_products": "declining products (true/false)",
    "phase_2_5_chain.upstream": "upstream suppliers",
    "phase_2_5_chain.midstream_company": "company role in chain",
    "phase_2_5_chain.downstream": "downstream customers",
    "phase_2_5_chain.business_model": "how they make money",
    "phase_2_6_customers.key_customers": "list of key customers",
    "phase_2_6_customers.validation.pays_real": "yes/no/unknown",
    "phase_2_6_customers.validation.repeat": "yes/no/unknown",
    "phase_2_6_customers.validation.to_production": "yes/no/unknown",
    "phase_2_6_customers.validation.concentrated": "low/medium/high/unknown",
    "phase_2_7_competitors.direct": "direct competitors list",
    "phase_2_7_competitors.indirect": "indirect competitors list",
    "phase_2_7_competitors.substitutes": "substitute technologies",
    "phase_2_7_competitors.insourcing": "customer self-build risk",
    "phase_2_7_competitors.financial": "financial comparison list",
    "phase_2_8_financials.revenue": "TTM revenue",
    "phase_2_8_financials.growth": "YoY growth",
    "phase_2_8_financials.margin": "gross/operating margin",
    "phase_2_8_financials.fcf": "FCF + FCF yield",
    "phase_2_9_valuation.market_cap": "market cap",
    "phase_2_9_valuation.ev_ebitda": "EV/EBITDA",
    "phase_2_9_valuation.current_pe": "P/E",
    "phase_2_9_valuation.implied_growth": "implied growth from current price",
    "phase_2_10_catalysts.operational": "operational catalysts list",
    "phase_2_10_catalysts.financial": "financial catalysts list",
    "phase_2_10_catalysts.narrative": "narrative catalysts list",
    "phase_2_10_catalysts.structural": "structural catalysts list",
    "phase_3_cycle.summary": "early_reversal | mid_confirmation | late_euphoria | peak_late | unclear",
    "phase_3_cycle.description": "cycle position detail",
    "phase_3_2_checklist.supply": "supply-side verdict + detail",
    "phase_3_2_checklist.demand": "demand-side verdict + detail",
    "phase_3_2_checklist.company": "company-side verdict + detail",
    "phase_3_2_checklist.competition": "competition-side verdict + detail",
    "phase_3_2_checklist.market": "market-side verdict + detail",
    "phase_3_2_checklist.valuation": "valuation-side verdict + detail",
    "phase_3_2_checklist.failure": "failure-condition verdict + detail",
    "phase_3_3_invalidation": "list of specific invalidation conditions",
    "phase_5_monitoring.next_earnings": "next earnings date",
    "phase_5_monitoring.current_quarter_guidance": "current quarter guidance",
    "phase_5_monitoring.key_metrics_next_quarter": "3-6 key metrics list",
    "phase_5_monitoring.product_milestones": "product/customer/order milestones",
    "phase_5_monitoring.valuation_assumptions_to_validate": "valuation assumptions to validate",
    "phase_5_monitoring.buy_thesis_failure": "buy thesis failure conditions",
    "phase_5_monitoring.sell_reduce_conditions": "sell/reduce conditions",
    "phase_5_monitoring.data_quality.a_pct": "A-tier data percentage 0-100",
    "phase_5_monitoring.data_quality.b_pct": "B-tier data percentage",
    "phase_5_monitoring.data_quality.c_pct": "C-tier data percentage",
    "phase_5_monitoring.data_quality.d_pct": "D-tier data percentage",
    "phase_5_monitoring.data_quality.verdict": "A+/A/A-/B+/B/B-/C/D quality verdict",
    "phase_5_monitoring.data_quality.tier_breakdown": "tier breakdown narrative",
}

def load_env(path):
    env = {}
    if not os.path.isfile(path):
        return env
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("\"'")
    return env


def fetch_url(url, timeout=12, user_agent=None):
    ua = user_agent or os.environ.get(
        "ER_USER_AGENT",
        "EquityResearch Dashboard research@er-dashboard.local"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def compact_source_text(html, limit=3500):
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;?", "&", text)
    text = re.sub(r"&lt;?", "<", text)
    text = re.sub(r"&gt;?", ">", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def add_research_source(out, name, url, limit=3500):
    sources = out.setdefault("research_sources", [])
    try:
        raw = fetch_url(url)
        sources.append({
            "name": name,
            "url": url,
            "text": compact_source_text(raw, limit=limit),
        })
        return raw
    except Exception as e:
        sources.append({
            "name": name,
            "url": url,
            "error": str(e)[:180],
        })
        return ""


def fetch_sec_recent_filings(ticker, out):
    """Fetch SEC submissions + companyfacts; do XBRL extraction inline so we
    don't ship the full companyfacts blob to the LLM."""
    out.setdefault("sec_financials", {"available": False, "reason": "fetch not started"})
    try:
        raw = fetch_url("https://www.sec.gov/files/company_tickers.json", timeout=15)
        companies = json.loads(raw)
    except Exception as e:
        out.setdefault("research_sources", []).append({
            "name": "sec_company_tickers",
            "url": "https://www.sec.gov/files/company_tickers.json",
            "error": str(e)[:180],
        })
        return

    cik = None
    company_title = None
    for item in companies.values():
        if str(item.get("ticker", "")).upper() == ticker.upper():
            cik = int(item.get("cik_str"))
            company_title = item.get("title")
            break
    if not cik:
        out.setdefault("research_sources", []).append({
            "name": "sec_company_tickers",
            "url": "https://www.sec.gov/files/company_tickers.json",
            "error": "ticker not found in SEC mapping",
        })
        return

    sec_url = "https://data.sec.gov/submissions/CIK{:010d}.json".format(cik)
    try:
        data = json.loads(fetch_url(sec_url, timeout=15))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])
        rows = []
        for idx, form in enumerate(forms[:12]):
            rows.append("{} {} {}".format(
                dates[idx] if idx < len(dates) else "",
                form,
                accessions[idx] if idx < len(accessions) else "",
            ).strip())
        out.setdefault("research_sources", []).append({
            "name": "sec_recent_filings",
            "url": sec_url,
            "company": company_title or ticker,
            "text": "\n".join(rows) or "SEC recent filings empty",
        })
        facts_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json".format(cik)
        try:
            facts_payload = json.loads(fetch_url(facts_url, timeout=20))
            # 1. Deterministic structured extraction — the only consumer of the
            #    full facts blob. Runs locally, no LLM, no extra requests.
            try:
                extracted = extract_sec_financial_metrics(facts_payload)
                extracted["source_url"] = facts_url
                out["sec_financials"] = extracted
            except Exception as exc:
                out["sec_financials"] = {
                    "available": False,
                    "reason": "extract failed: {}".format(str(exc)[:160]),
                }
            # 2. Trimmed LLM-friendly digest: same tags, fewer entries, capped.
            #    This stays in research_sources because the LLM may still want
            #    to read the literal numbers for narrative context.
            wanted = set()
            for tags in SEC_FINANCIAL_TAGS.values():
                wanted.update(tags)
            wanted.update({
                "LongTermDebt", "StockholdersEquity", "CommonStockSharesOutstanding",
                "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            })
            fact_rows = []
            for taxonomy in ("us-gaap", "ifrs-full"):
                for tag, fact in facts_payload.get("facts", {}).get(taxonomy, {}).items():
                    if tag not in wanted:
                        continue
                    entries = []
                    for unit_rows in fact.get("units", {}).values():
                        entries.extend(unit_rows)
                    entries = [row for row in entries if row.get("form") in SEC_FORMS]
                    entries.sort(key=lambda row: (row.get("filed", ""), row.get("end", "")), reverse=True)
                    if entries:
                        fact_rows.append({
                            "tag": tag,
                            "label": fact.get("label", tag),
                            "recent": entries[:6],
                        })
            out.setdefault("research_sources", []).append({
                "name": "sec_companyfacts",
                "url": facts_url,
                "text": json.dumps(fact_rows, ensure_ascii=False)[:20000],
            })
        except Exception as exc:
            out["sec_financials"] = {
                "available": False,
                "reason": "fetch failed: {}".format(str(exc)[:160]),
            }
            out.setdefault("research_sources", []).append({
                "name": "sec_companyfacts",
                "url": facts_url,
                "error": str(exc)[:180],
            })
        filing_count = 0
        for idx, form in enumerate(forms):
            if form not in ("10-K", "10-Q", "20-F", "6-K", "8-K"):
                continue
            if idx >= len(accessions) or idx >= len(primary_documents):
                continue
            accession = str(accessions[idx]).replace("-", "")
            document = primary_documents[idx]
            filing_url = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(cik, accession, document)
            add_research_source(
                out,
                "sec_{}_{}".format(form.lower().replace("-", ""), dates[idx] if idx < len(dates) else idx),
                filing_url,
                limit=8500,
            )
            filing_count += 1
            if filing_count >= 3:
                break
    except Exception as e:
        out.setdefault("research_sources", []).append({
            "name": "sec_recent_filings",
            "url": sec_url,
            "error": str(e)[:180],
        })


def add_fmp_sources(ticker, out):
    api_key = load_env(DSA_ENV_PATH).get("FMP_API_KEY", "")
    if not api_key:
        return False
    statement_success = 0
    endpoints = (
        ("fmp_profile", "profile", 2),
        ("fmp_income_quarter", "income-statement", 8),
        ("fmp_balance_quarter", "balance-sheet-statement", 8),
        ("fmp_cashflow_quarter", "cash-flow-statement", 8),
        ("fmp_key_metrics", "key-metrics", 8),
        ("fmp_ratios", "ratios", 8),
        ("fmp_estimates", "analyst-estimates", 8),
    )
    for name, endpoint, limit in endpoints:
        url = "https://financialmodelingprep.com/stable/{}?symbol={}&limit={}&apikey={}".format(
            endpoint, urllib.parse.quote(ticker), limit, urllib.parse.quote(api_key)
        )
        try:
            raw = fetch_url(url, timeout=18)
            data = json.loads(raw)
            public_url = url.split("&apikey=", 1)[0]
            out.setdefault("research_sources", []).append({
                "name": name,
                "url": public_url,
                "text": json.dumps(data, ensure_ascii=False)[:10000],
            })
            if name == "fmp_profile" and isinstance(data, list) and data:
                profile = data[0]
                for source_key, target_key in (
                    ("price", "price"), ("mktCap", "market_cap"), ("companyName", "company_name"),
                    ("exchange", "exchange"), ("industry", "industry"), ("change", "price_change"),
                    ("changePercentage", "price_change_pct"),
                ):
                    if profile.get(source_key) not in (None, ""):
                        out[target_key] = profile[source_key]
                price_range = str(profile.get("range") or "")
                range_match = re.fullmatch(r"\s*([\d,.]+)\s*-\s*([\d,.]+)\s*", price_range)
                if range_match:
                    out["wk52_low"] = range_match.group(1).replace(",", "")
                    out["wk52_high"] = range_match.group(2).replace(",", "")
            elif isinstance(data, list) and data:
                statement_success += 1
        except Exception as exc:
            out.setdefault("research_sources", []).append({
                "name": name,
                "url": "FMP stable/{}".format(endpoint),
                "error": str(exc)[:180],
            })
    return statement_success > 0


def add_alpha_vantage_sources(ticker, out):
    api_key = load_env(DSA_ENV_PATH).get("ALPHAVANTAGE_API_KEY", "")
    if not api_key:
        return
    for function in ("OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"):
        url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode({
            "function": function, "symbol": ticker, "apikey": api_key,
        })
        try:
            payload = json.loads(fetch_url(url, timeout=25))
            if payload.get("Note") or payload.get("Information") or payload.get("Error Message"):
                raise RuntimeError(payload.get("Note") or payload.get("Information") or payload.get("Error Message"))
            out.setdefault("research_sources", []).append({
                "name": "alphavantage_{}".format(function.lower()),
                "url": "Alpha Vantage {} for {}".format(function, ticker),
                "text": json.dumps(payload, ensure_ascii=False)[:18000],
            })
            if function == "OVERVIEW":
                for source_key, target_key in (
                    ("Name", "company_name"), ("Exchange", "exchange"), ("Industry", "industry"),
                    ("MarketCapitalization", "market_cap"), ("PERatio", "pe_ttm"),
                    ("ForwardPE", "fwd_pe"), ("52WeekHigh", "wk52_high"), ("52WeekLow", "wk52_low"),
                ):
                    if payload.get(source_key) not in (None, "", "None"):
                        out[target_key] = payload[source_key]
        except Exception as exc:
            out.setdefault("research_sources", []).append({
                "name": "alphavantage_{}".format(function.lower()),
                "url": "Alpha Vantage {} for {}".format(function, ticker),
                "error": str(exc)[:180],
            })


def add_search_sources(ticker, out):
    queries = (
        "{} latest earnings investor relations revenue guidance".format(ticker),
        "{} business products customers competitors industry chain".format(ticker),
        "{} latest news catalyst risk valuation".format(ticker),
    )
    for index, query in enumerate(queries, 1):
        url = "http://127.0.0.1:8081/search?" + urllib.parse.urlencode({
            "q": query, "format": "json", "language": "en-US", "safesearch": "0",
        })
        try:
            payload = json.loads(fetch_url(url, timeout=20))
            rows = []
            for result in payload.get("results", [])[:8]:
                rows.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", ""),
                    "publishedDate": result.get("publishedDate", ""),
                })
            out.setdefault("research_sources", []).append({
                "name": "search_{}".format(index),
                "url": "SearXNG: " + query,
                "text": json.dumps(rows, ensure_ascii=False)[:10000],
            })
        except Exception as exc:
            out.setdefault("research_sources", []).append({
                "name": "search_{}".format(index),
                "url": "SearXNG: " + query,
                "error": str(exc)[:180],
            })


def fetch_stock_data(ticker):
    slug = ticker.lower()
    url = f"https://stockanalysis.com/stocks/{slug}/"
    out = {"ticker": ticker.upper(), "source_url": url}
    html = add_research_source(out, "stockanalysis_overview", url)
    for name, suffix in (
        ("stockanalysis_financials", "financials/"),
        ("stockanalysis_statistics", "statistics/"),
        ("stockanalysis_forecast", "forecast/"),
    ):
        add_research_source(out, name, "https://stockanalysis.com/stocks/{}/{}".format(slug, suffix), limit=2600)
    fmp_has_statements = add_fmp_sources(ticker, out)
    if not fmp_has_statements:
        add_alpha_vantage_sources(ticker, out)
    fetch_sec_recent_filings(ticker, out)
    add_search_sources(ticker, out)
    if not html:
        out["fetch_error"] = "stockanalysis overview unavailable"
        return out
    patterns = {
        "price": r'class="text-3xl[^>]*">\$?([\d,]+\.\d+)',
        "market_cap": r'Market Cap[^<]*</[^>]*>[^<]*</[^>]*>\$?([\d.]+[TBMK]?)',
        "pe_ttm": r'P/E[^<]*</[^>]*>[^<]*</[^>]*>([\d.]+)',
        "fwd_pe": r'Forward P/E[^<]*</[^>]*>[^<]*</[^>]*>([\d.]+)',
        "revenue_growth": r'Revenue Growth[^<]*</[^>]*>([+\-]?[\d.]+%?)',
        "gross_margin": r'Gross Margin[^<]*</[^>]*>([\d.]+%)',
        "fcf_yield": r'FCF Yield[^<]*</[^>]*>([\d.]+%)',
        "wk52_high": r'52-Wk High[^<]*</[^>]*>\$?([\d,.]+)',
        "wk52_low": r'52-Wk Low[^<]*</[^>]*>\$?([\d,.]+)',
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, html)
        if m:
            out[key] = m.group(1).replace(",", "")
    return out


def trim_stock_data_for_prompt(stock_data, per_source_limit=1400, max_sources=5):
    trimmed = {}
    for key, value in stock_data.items():
        if key == "research_sources":
            continue
        trimmed[key] = value
    sources = []
    for source in stock_data.get("research_sources", [])[:max_sources]:
        item = dict(source)
        if "text" in item:
            item["text"] = str(item["text"])[:per_source_limit]
        sources.append(item)
    if sources:
        trimmed["research_sources"] = sources
    return trimmed


def template_placeholders():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", template)))


def html_escape(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def list_to_li(items):
    if isinstance(items, str):
        items = [items]
    return "\n".join(f"<li>{html_escape(x)}</li>" for x in (items or ["未披露 / 待验证"]))


def rows_to_html(rows, cols=2):
    if isinstance(rows, str):
        return rows
    if not rows:
        return "<tr>" + "".join("<td>未披露 / 待验证</td>" for _ in range(cols)) + "</tr>"
    out = []
    for row in rows:
        if isinstance(row, dict):
            vals = list(row.values())
        elif isinstance(row, (list, tuple)):
            vals = row
        else:
            vals = [row]
        out.append("<tr>" + "".join(f"<td>{html_escape(v)}</td>" for v in vals) + "</tr>")
    return "\n".join(out)


def normalize_model_row_html(field, value):
    expected_cols = len(ROW_SCHEMAS[field])
    if not isinstance(value, str):
        value = rows_to_html(value, cols=expected_cols)
    raw = html.unescape(html.unescape(value))
    row_blocks = re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", raw)
    normalized = []
    for block in row_blocks:
        if re.search(r"(?is)<th[^>]*>", block):
            continue
        cells = re.findall(r"(?is)<td[^>]*>(.*?)</td>", block)
        if len(cells) != expected_cols:
            return None
        clean_cells = []
        for cell in cells:
            text = re.sub(r"(?s)<[^>]+>", " ", html.unescape(cell))
            text = re.sub(r"\s+", " ", text).strip()
            clean_cells.append("<td>{}</td>".format(html_escape(text or "未披露 / 待验证")))
        normalized.append("<tr>{}</tr>".format("".join(clean_cells)))
    if not normalized:
        return None
    return "\n".join(normalized)


def clean_model_field(field, value):
    if field in ROW_SCHEMAS:
        return normalize_model_row_html(field, value)
    return value


def plain_display_text(value):
    text = re.sub(r"(?s)<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def compact_metric(value, metric_type):
    text = plain_display_text(value)
    if not text:
        return UNKNOWN_DISPLAY
    unknown_markers = ("未披露", "待验证", "未抓取", "无法获取", "接口 402", "接口402", "请求失败")
    if any(marker in text for marker in unknown_markers):
        return UNKNOWN_DISPLAY
    if len(text) <= 24:
        return text
    patterns = {
        "percent": r"[+\-]?\d+(?:\.\d+)?\s*%",
        "currency": r"[$¥€]\s*[\d,.]+(?:\s*(?:T|B|M|K|万亿|亿|万))?",
        "multiple": r"[+\-]?\d+(?:\.\d+)?\s*[xX倍]",
        "number": r"^[+\-]?[\d,.]+(?:\.\d+)?",
    }
    match = re.search(patterns[metric_type], text)
    return re.sub(r"\s+", "", match.group(0)) if match else UNKNOWN_DISPLAY


def compact_dashboard_display(data):
    for field, metric_type in SHORT_DISPLAY_FIELDS.items():
        data[field] = compact_metric(data.get(field), metric_type)
    return data


def contains_prohibited_advice(value):
    text = plain_display_text(value).lower()
    return any(term.lower() in text for term in PROHIBITED_ADVICE_TERMS)


def strip_prohibited_advice_value(value):
    if isinstance(value, list):
        kept = [item for item in value if not contains_prohibited_advice(item)]
        return kept or [UNKNOWN_DISPLAY]
    if not isinstance(value, str) or not contains_prohibited_advice(value):
        return value
    text = value
    for tag in ("li", "tr", "p"):
        text = re.sub(
            r"(?is)<{0}[^>]*>.*?</{0}>".format(tag),
            lambda match: "" if contains_prohibited_advice(match.group(0)) else match.group(0),
            text,
        )
    if contains_prohibited_advice(text):
        tokens = re.split(r"([。！？!?；;])", text)
        parts = [tokens[index] + (tokens[index + 1] if index + 1 < len(tokens) else "") for index in range(0, len(tokens), 2)]
        text = "".join(part for part in parts if not contains_prohibited_advice(part))
    return text.strip() or UNKNOWN_DISPLAY


def remove_prohibited_advice(data):
    for field in ("action_class", "action_label", "action_rationale"):
        data.pop(field, None)
    for field, value in list(data.items()):
        data[field] = strip_prohibited_advice_value(value)
    return data


def default_dashboard(ticker, stock_data, reason="待生成"):
    today = time.strftime("%Y-%m-%d")
    analysis_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    d = {k: "未披露 / 待验证" for k in template_placeholders()}
    d.update({
        "TICKER": ticker, "company_name": ticker, "exchange": "US", "industry": "待识别", "current_date": today,
        "analysis_timestamp": analysis_timestamp,
        "current_price": stock_data.get("price", "N/A"), "market_cap": stock_data.get("market_cap", "未披露 / 待验证"),
        "phase_1_intent": "observe", "phase_1_horizon": "mid_term", "phase_1_security_type": "common_stock",
        "phase_1_core_question": "用户要求 ER 深度分析",
        "forward_pe": stock_data.get("fwd_pe", "未披露 / 待验证"), "ev_sales": "未披露 / 待验证", "forward_ev_sales": "未披露 / 待验证",
        "conclusion_class": "warn", "one_liner": f"{ticker} 已进入 ER skill 深度研究流程；当前数据不足，部分结论待验证。",
        "company_definition": "待按 Equity Research skill Phase 2.1 补全：公司卖什么、客户是谁、行业归属和增长逻辑。",
        "investment_thesis": "待交叉验证：需要公司一手披露、SEC/IR、市场数据和行业数据共同验证。",
        "price_implication": "当前价格隐含增长尚未完成测算；不得用故事替代估值。",
        "chain_overview": "按真实产业链拆分，不默认套 AI。", "industry_chain_classification": "待识别真实产业链", "profit_type": "待验证赚钱模式",
        "business_quarter_label": "最近季度", "business_summary": "业务结构需按分部列收入、占比、同比、环比和投资含义。",
        "business_analogies": "<p>以下类比便于理解,非客观数据。</p>", "product_analogy_box": "<p>以下类比便于理解,非客观数据。</p>",
        "data_sources": ["公司 IR / SEC 待补", stock_data.get("source_url", "stockanalysis.com")], "data_conflicts": ["单源结论待交叉验证"],
        "monitoring_metrics": ["下一季收入与指引", "毛利率 / FCF", "订单 / backlog / RPO", "估值倍数变化"],
        "product_milestones": ["产品交付 / 客户订单节点待验证"], "valuation_assumptions": ["当前估值隐含增长需验证"],
        "invalidation_conditions": ["收入或指引低于 thesis 假设", "毛利率 / FCF 恶化", "关键客户或订单不成立"],
        "sell_conditions": ["估值透支且基本面不再上修", "竞争或客户自研风险兑现"],
    })
    for field in ROW_FIELDS:
        d[field] = "<tr><td>未披露 / 待验证</td><td>需要来源补充</td></tr>"
    for field in CLASS_FIELDS:
        d.setdefault(field, "warn")
    d.setdefault("price_change_symbol", "")
    return d


def build_prompt(ticker, stock_data, compact=False, fields_override=None, stage_name="完整研究"):
    fields = fields_override or template_placeholders()
    row_schemas = {field: ROW_SCHEMAS[field] for field in fields if field in ROW_SCHEMAS}
    short_fields = {field: SHORT_DISPLAY_FIELDS[field] for field in fields if field in SHORT_DISPLAY_FIELDS}
    today = time.strftime("%Y-%m-%d")
    analysis_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    skill = SKILL_PATH.read_text(encoding="utf-8")
    if not all(x in skill for x in ("Phase 1：定问题", "Phase 2：研究层", "Phase 3：动作层", "Phase 5：监控清单", "Hard rules")):
        raise RuntimeError("equity-research SKILL.md missing required sections")
    skill_digest = """
你是 equity-research 完整工作流中的单阶段执行器。程序会按顺序分别完成公司概览、财务估值、业务产业链、竞对客户、周期与监控五个阶段；你只完成当前阶段和当前字段,不要重新规划整套报告,不要输出提纲。
研究纪律:
1. 数字只用提供的来源,必须保留日期和口径；找不到写“未披露 / 待验证”,禁止猜测。
2. 公司一手披露/SEC > FMP/Alpha Vantage/StockAnalysis > 搜索摘要。禁止用模型记忆补数字、日期、客户协议、并购或产能事实。
3. 单源结论标“待交叉验证”；数据冲突要列明,不强行选一个。
4. 不写“某某等/等等/其他等”；产品、客户、业务尽量列全。
5. 先判断真实产业链,不默认套 AI。
6. 输出应是可直接发布的正式看板内容,不是“待补充”的骨架。
7. 直接完成字段并返回 JSON；无需展示思考过程。
8. 本报告只用于了解公司，不提供投资建议。禁止输出目标价、买入价/买入点、止损价/止损位、止盈价/止盈位、仓位或加减仓建议。
""".strip()
    compact_rules = """
压缩输出规则:
- 这是 JSON 重试模式,必须输出完整闭合 JSON,不能被截断。
- 每个普通文本字段控制在 60-120 个中文字符。
- 每个 *_rows 字段最多 4 行,每个 td 最多 45 个中文字符。
- 不要输出 markdown_report,不要输出长篇解释。
""".strip() if compact else ""

    return f"""{skill_digest}

股票: {ticker}
当前研究阶段: {stage_name}
当前日期: {today}
分析时间戳: {analysis_timestamp}
高优先级最新抓取源(JSON): {json.dumps(stock_data, ensure_ascii=False)}
{compact_rules}

你只输出 JSON,不要 markdown fence。必须给 dashboard_data,覆盖以下模板字段:
{json.dumps(fields, ensure_ascii=False)}
本批表格字段的固定列定义:
{json.dumps(row_schemas, ensure_ascii=False)}
本批短展示字段（只能返回一个数值/百分比/倍数，不得附加来源说明或错误原因）:
{json.dumps(short_fields, ensure_ascii=False)}

JSON 格式:
{{"dashboard_data":{{...仅包含本批明确列出的模板字段...}}}}

字段规则:
- dashboard_data 只能包含本批明确列出的字段,禁止添加任何额外字段。
- 普通文本字段控制在 60-160 个中文字符；表格每个单元格保持简洁。
- 短展示字段只写可直接放进 KPI 卡片的短值，例如 21.1、+3.2%、$4.8B；无法核验时只写“未披露 / 待验证”。来源、口径和接口错误写入 data_sources/data_conflicts，禁止塞进短展示字段。
- *_rows 字段只能输出 HTML <tr><td>...</td></tr> 字符串,禁止输出 <th>；每行 td 数量必须严格等于固定列定义。
- monitoring_metrics/product_milestones/valuation_assumptions/invalidation_conditions/sell_conditions/data_conflicts/data_sources 输出 list。
- class 字段只能用 pos/neg/warn。
- 必须真正完成当前阶段的研究和解释,不是生成提纲或索引。未找到的数据写“未披露 / 待验证”,不能编造。
- 禁止输出“快速版未覆盖”“需要按 skill 补充”“待生成”。如果来源不足,要说明查过哪些来源及缺口。
- 内容质量要接近正式 ER 看板,像 GLW 示例那样有业务、产品、产业链、竞对、客户验证、催化剂和监控。
- current_date 必须等于 {today}; analysis_timestamp 必须等于 {analysis_timestamp}。禁止输出历史分析时间。
- 不要复用旧报告、旧结论或旧页脚；如果某个最新财报/价格/估值数据无法核验,标注“未披露 / 待验证”并说明数据源缺口。
- 优先使用 high-priority JSON 里的 research_sources；公司 IR/SEC 正文、FMP、StockAnalysis 和最新搜索结果高于模型记忆。
- 搜索摘要只能用于发现线索和定性描述,不能单独支撑精确数字、客户合同、并购状态或明确日期。
- 如果 research_sources 全部失败,必须在 data_sources/data_conflicts 里说明“实时源抓取失败”,不得装作已完整验证。
"""


def call_llm(ticker, stock_data, env):
    api_key = env.get("LLM_MINIMAX_API_KEY") or env.get("MINIMAX_API_KEYS", "") or env.get("MINIMAX_API_KEY", "")
    base_url = env.get("LLM_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1").rstrip("/")
    model = env.get("LLM_MINIMAX_MODELS") or env.get("LITELLM_MODEL") or "MiniMax-M3"
    model = model.split(",")[0].strip().split("/")[-1]
    if not api_key:
        return None, "no API key"

    def extract_json(content):
        original_content = content
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        start = content.find("{")
        if start < 0:
            return None, "no JSON object in model content", content
        depth = 0
        end = -1
        in_str = False
        esc = False
        for i, ch in enumerate(content[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
        if end < 0:
            comma_positions = []
            depth = 0
            in_str = False
            esc = False
            for i, ch in enumerate(content[start:], start):
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    elif ch == "," and depth == 2:
                        comma_positions.append(i)
            for comma_at in reversed(comma_positions):
                try:
                    repaired = json.loads(content[start:comma_at] + "}}")
                    if isinstance(repaired, dict) and isinstance(repaired.get("dashboard_data"), dict):
                        return repaired, None, original_content
                except Exception:
                    continue
            return None, "unbalanced JSON object in model content", original_content
        try:
            return json.loads(content[start:end]), None, content
        except Exception as parse_err:
            return None, "JSON parse failed: " + str(parse_err)[:160], content

    def request_json(prompt, max_tokens, timeout=180, reasoning_split=True):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是严格执行 Claude SKILL.md 的股票研究助手。只输出完整闭合 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "reasoning_split": reasoning_split,
        }
        req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key})
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        response = json.loads(raw)
        choice = response["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        if not content and "{" in str(message.get("reasoning") or ""):
            content = message.get("reasoning") or ""
        if not content:
            return None, "empty model content (finish_reason={})".format(choice.get("finish_reason")), ""
        return extract_json(content)

    merged = {"dashboard_data": {}}
    total_stages = len(FULL_RESEARCH_FIELD_GROUPS)
    for stage_index, (stage_name, fields) in enumerate(FULL_RESEARCH_FIELD_GROUPS, 1):
        print("ER_STAGE {}/{} {}".format(stage_index, total_stages, stage_name), flush=True)
        chunks = split_field_batches(fields)
        for chunk_index, chunk in enumerate(chunks, 1):
            print("ER_BATCH {}/{} {} {}/{}".format(stage_index, total_stages, stage_name, chunk_index, len(chunks)), flush=True)
            prompt_data = trim_stock_data_for_prompt(stock_data, per_source_limit=900, max_sources=24)
            if merged["dashboard_data"]:
                prompt_data["completed_stage_data"] = merged["dashboard_data"]
            try:
                prompt = build_prompt(
                    ticker,
                    prompt_data,
                    compact=True,
                    fields_override=chunk,
                    stage_name="{} ({}/{})".format(stage_name, chunk_index, len(chunks)),
                )
                obj, err, raw_content = request_json(prompt, max_tokens=9000, timeout=300)
                if err and "finish_reason=length" in err:
                    print(
                        "ER_RETRY {}/{} {} {}/{} no-reasoning".format(
                            stage_index, total_stages, stage_name,
                            chunk_index, len(chunks)),
                        flush=True,
                    )
                    obj, err, raw_content = request_json(
                        prompt,
                        max_tokens=9000,
                        timeout=300,
                        reasoning_split=False,
                    )
                if err:
                    Path("/tmp/er-llm-last.txt").write_text(raw_content[:20000], encoding="utf-8")
                    return None, "{} batch {}/{} JSON failed: {}".format(stage_name, chunk_index, len(chunks), err)
                data = obj.get("dashboard_data", obj) if isinstance(obj, dict) else {}
                if not isinstance(data, dict):
                    return None, "{} batch {}/{} missing dashboard_data".format(stage_name, chunk_index, len(chunks))
                data = {field: clean_model_field(field, data.get(field)) for field in chunk}
                missing = [field for field in chunk if data.get(field) in (None, "", [], {})]
                if missing:
                    retry_data = trim_stock_data_for_prompt(stock_data, per_source_limit=600, max_sources=24)
                    retry_data["completed_stage_data"] = dict(merged["dashboard_data"], **data)
                    retry_prompt = build_prompt(
                        ticker,
                        retry_data,
                        compact=True,
                        fields_override=missing,
                        stage_name=stage_name + "缺失字段补全",
                    )
                    retry_obj, retry_err, retry_raw = request_json(retry_prompt, max_tokens=7000, timeout=300)
                    if retry_err:
                        Path("/tmp/er-llm-last.txt").write_text(retry_raw[:20000], encoding="utf-8")
                        return None, "{} incomplete and retry failed: {}".format(stage_name, retry_err)
                    retry_values = retry_obj.get("dashboard_data", retry_obj) if isinstance(retry_obj, dict) else {}
                    if isinstance(retry_values, dict):
                        data.update({field: clean_model_field(field, retry_values.get(field)) for field in missing})
                    missing = [field for field in chunk if data.get(field) in (None, "", [], {})]
                    if missing:
                        return None, "{} still missing fields: {}".format(stage_name, ",".join(missing))
                merged["dashboard_data"].update({field: data[field] for field in chunk})
            except urllib.error.HTTPError as e:
                return None, "{} HTTP {}: {}".format(stage_name, e.code, e.read().decode("utf-8", errors="ignore")[:300])
            except Exception as e:
                return None, "{} request failed: {}".format(stage_name, str(e)[:300])
    return merged, None


def _row_html(cells):
    """Build a single row of HTML cells, preserving ROW_SCHEMAS column counts."""
    return "<tr>" + "".join("<td>{}</td>".format(html_escape(c or UNKNOWN_DISPLAY))
                            for c in cells) + "</tr>"


def _metric_scope_label(fact):
    """Render the period that a SEC fact came from (single quarter vs YTD)."""
    if not fact:
        return ""
    scope = fact.get("scope") or ""
    start = fact.get("period_start") or ""
    end = fact.get("period_end") or ""
    if not end:
        return ""
    if scope == "q":
        return "Q {}–{}".format(start or "?", end)
    if scope == "ytd":
        return "YTD {}–{}".format(start or "?", end)
    if scope == "fy":
        return "FY {}".format(end[:4])
    return "{}–{}".format(start, end)


def _sec_quarter_row(label, anchor_fact, prior_fact=None, ratio_pct=None):
    """Build a latest_quarter_rows cell tuple. Prior column is the prior-year
    same-quarter fact (YoY comparable); the Q/Q column is deliberately left
    as UNKNOWN_DISPLAY until a proper prior-quarter selector exists."""
    cur = format_currency(anchor_fact.get("val")) if anchor_fact else None
    prev = format_currency(prior_fact.get("val")) if prior_fact else None
    swing_cell = UNKNOWN_DISPLAY
    if ratio_pct is not None:
        swing_cell = "{:+.1f}%".format(ratio_pct)
    elif anchor_fact and prior_fact:
        try:
            cur_val = float(anchor_fact.get("val"))
            prior_val = float(prior_fact.get("val"))
            if prior_val < 0 and cur_val > 0:
                swing_cell = "扭亏 +" + format_currency(cur_val - prior_val)
            elif abs(prior_val) > 0 and ((cur_val >= 0) == (prior_val >= 0)):
                pct = ((cur_val - prior_val) / abs(prior_val)) * 100.0
                swing_cell = "{:+.1f}%".format(pct)
        except (TypeError, ValueError):
            pass
    # Header order is ["指标", "上年同期", "本季度", "同比", ...] — make
    # sure cell positions follow the updated ROW_SCHEMAS exactly.
    cells = [label, prev or UNKNOWN_DISPLAY, cur or UNKNOWN_DISPLAY,
             swing_cell,
             UNKNOWN_DISPLAY, _metric_scope_label(anchor_fact)]
    return _row_html(cells)


def _build_sec_balance_sheet_rows(sec_fin):
    """balance_sheet_rows: only include items SEC actually disclosed."""
    out_rows = []
    for row in (sec_fin.get("balance_sheet") or []):
        value = row.get("value")
        if value is None:
            continue
        yoy_pct = row.get("yoy_change_pct")
        yoy_cell = ("{:+.1f}%".format(yoy_pct)
                    if isinstance(yoy_pct, (int, float)) else MISSING_TO_CROSS_VERIFY)
        period = row.get("period_end") or ""
        comment = "SEC {} ({})".format(row.get("form") or "filing",
                                       period)
        out_rows.append(_row_html([
            row.get("label") or UNKNOWN_DISPLAY,
            format_currency(value) or UNKNOWN_DISPLAY,
            yoy_cell,
            comment,
        ]))
    if not out_rows:
        out_rows.append(_row_html(["Total Assets", MISSING_NOT_DISCLOSED, MISSING_NOT_DISCLOSED,
                                    "SEC 10-Q 未抓取到"]))
    return "\n".join(out_rows)


def _build_sec_quarterly_rows(sec_fin):
    """latest_quarter_rows: build deterministically from SEC metrics."""
    metrics = (sec_fin or {}).get("metrics") or {}
    q_end = (sec_fin or {}).get("latest_quarter_end") or ""
    fy = None
    fp = None
    rev = metrics.get("revenue") or {}
    anchor = rev.get("latest_q") or {}
    if anchor:
        fy = anchor.get("fy")
        fp = anchor.get("fp")
    period_label = ""
    if fy and fp:
        period_label = "FY{} {}".format(fy, fp)
    elif (sec_fin or {}).get("latest_quarter_label"):
        period_label = sec_fin.get("latest_quarter_label")
    rows = []
    rev_q = anchor
    rev_yoy = (rev.get("yoy_q") or {}) if rev else {}
    rev_yoy_pct = rev.get("q_yoy_pct") if rev else None
    if rev_q:
        rows.append(_sec_quarter_row(
            "Revenue (本季度)", rev_q, rev_yoy, rev_yoy_pct))

    gp_m = metrics.get("gross_profit") or {}
    gp_q = gp_m.get("latest_q")
    gp_yoy = gp_m.get("yoy_q")
    gp_yoy_pct = gp_m.get("q_yoy_pct")
    if gp_q:
        rows.append(_sec_quarter_row(
            "Gross Profit (本季度)", gp_q, gp_yoy, gp_yoy_pct))

    rev_val = (rev_q or {}).get("val")
    gp_val = (gp_q or {}).get("val")
    op_m = metrics.get("operating_income") or {}
    op_q = op_m.get("latest_q") or {}
    op_yoy = op_m.get("yoy_q") or {}
    if rev_val and gp_val:
        gm = safe_ratio(gp_val, rev_val)
        prior_rev = (rev_yoy or {}).get("val")
        prior_gp = (gp_yoy or {}).get("val")
        gm_prior = safe_ratio(prior_gp, prior_rev) if (prior_rev and prior_gp) else None
        delta = (gm - gm_prior) if (gm is not None and gm_prior is not None) else None
        gm_cell = "{:.2f}%".format(gm) if gm is not None else UNKNOWN_DISPLAY
        gm_period = "{}–{}".format((gp_q or {}).get("period_start", "?"),
                                    (gp_q or {}).get("period_end", "?"))
        rows.append(_row_html([
            "Gross Margin", MISSING_NOT_DISCLOSED,
            gm_cell, ("{:+.2f} pp".format(delta)
                      if delta is not None else UNKNOWN_DISPLAY),
            "vs 预期 不适用", gm_period
        ]))

    rows.append(_sec_quarter_row("Operating Income", op_q, op_yoy))
    rows.append(_sec_quarter_row(
        "Net Income",
        (metrics.get("net_income") or {}).get("latest_q"),
        (metrics.get("net_income") or {}).get("yoy_q")))
    rows.append(_sec_quarter_row(
        "Diluted EPS",
        (metrics.get("eps_diluted") or {}).get("latest_q"),
        (metrics.get("eps_diluted") or {}).get("yoy_q")))

    if not rows:
        rows.append(_row_html(["Revenue", MISSING_NOT_DISCLOSED, MISSING_NOT_DISCLOSED,
                                MISSING_NOT_DISCLOSED, MISSING_NOT_DISCLOSED,
                                "SEC 未找到匹配季度 XBRL"]))
    return "\n".join(rows), period_label


def _build_sec_fy_rows(sec_fin):
    """fy_comparison_rows: only show FULL-FISCAL-YEAR data SEC explicitly
    disclosed.  YTD figures (which only span the months since the most
    recent FY start) must never appear in this table — they live in the
    Free Cash Flow KPI card instead, which is labeled YTD/TTM/FY."""
    metrics = (sec_fin or {}).get("metrics") or {}
    rows = []
    rev_fy = (metrics.get("revenue") or {}).get("fy") or {}
    rev_fy_val = rev_fy.get("val")
    if rev_fy_val is not None:
        period_end = rev_fy.get("period_end") or ""
        rows.append(_row_html([
            "Revenue",
            format_currency(rev_fy_val) or UNKNOWN_DISPLAY,
            MISSING_NOT_APPLICABLE if _is_recent_spinoff(period_end) else MISSING_INSUFFICIENT_HISTORY,
            UNKNOWN_DISPLAY,
        ]))
    gp_fy = (metrics.get("gross_profit") or {}).get("fy") or {}
    if gp_fy.get("val") is not None:
        rows.append(_row_html([
            "GAAP Gross Profit",
            format_currency(gp_fy["val"]) or UNKNOWN_DISPLAY,
            MISSING_NOT_APPLICABLE,
            UNKNOWN_DISPLAY,
        ]))
    op_fy = (metrics.get("operating_income") or {}).get("fy") or {}
    if op_fy.get("val") is not None:
        rows.append(_row_html([
            "Operating Income",
            format_currency(op_fy["val"]) or UNKNOWN_DISPLAY,
            MISSING_NOT_APPLICABLE,
            UNKNOWN_DISPLAY,
        ]))
    ni_fy = (metrics.get("net_income") or {}).get("fy") or {}
    if ni_fy.get("val") is not None:
        rows.append(_row_html([
            "GAAP Net Income",
            format_currency(ni_fy["val"]) or UNKNOWN_DISPLAY,
            MISSING_NOT_APPLICABLE,
            UNKNOWN_DISPLAY,
        ]))
    # FY cash-flow lines would be added here ONLY when SEC actually has the
    # 340-380 day FY block. We deliberately do NOT pull from metrics[...].ytd
    # here — see docstring.
    if not rows:
        rows.append(_row_html([
            "Revenue",
            MISSING_NOT_APPLICABLE,
            MISSING_NOT_APPLICABLE,
            "SEC 仅披露 10-Q 累计；完整 FY 待 10-K 公布",
        ]))
    return "\n".join(rows)


def _is_recent_spinoff(period_end_str):
    """Mark fields that depend on data SEC doesn't yet have for a recent ticker."""
    if not period_end_str:
        return False
    try:
        d = datetime.datetime.strptime(period_end_str[:10], "%Y-%m-%d").date()
    except Exception:
        return False
    return (datetime.date.today() - d).days < 730  # <2 yrs of SEC history


def _build_sec_business_rows(sec_fin, company_name):
    """Build the business_rows table. Without firm evidence of either
    segment dimensions in XBRL or a reportable-segment Note in the
    filing, we report consolidated company revenue — never assert
    "single reportable segment" as a fact the company did not state.

    The prior spell claimed SNDK "按单一报告分部披露" without citing the
    10-Q Note; that inference is removed. We surface the consolidated
    line plus a clear "non-segment" annotation so a reviewer knows the
    row is not a segment breakdown.
    """
    metrics = (sec_fin or {}).get("metrics") or {}
    rev_q = (metrics.get("revenue") or {}).get("latest_q") or {}
    rev_yoy_pct = (metrics.get("revenue") or {}).get("q_yoy_pct")
    if rev_q.get("val") is None:
        return _row_html([
            "{} 合并口径".format(company_name or "公司"),
            MISSING_NOT_DISCLOSED,
            MISSING_NOT_DISCLOSED,
            MISSING_NOT_DISCLOSED,
            MISSING_TO_CROSS_VERIFY,
            "SEC 未找到本季度 Revenue 标签",
        ])
    period_end = rev_q.get("period_end") or ""
    fy = rev_q.get("fy")
    fp = rev_q.get("fp")
    period_short = "FY{}{}".format(fy, fp) if (fy and fp) else ""
    val_text = "{} {}".format(period_short, format_currency(rev_q.get("val"))).strip()
    yoy_cell = "{:+.1f}%".format(rev_yoy_pct) if isinstance(rev_yoy_pct, (int, float)) else MISSING_NOT_DISCLOSED
    return _row_html([
        "{} 合并口径（非分部数据）".format(company_name or "公司"),
        val_text or UNKNOWN_DISPLAY,
        "不适用",
        yoy_cell,
        MISSING_TO_CROSS_VERIFY,
        "公司合并数据，不代表产品或报告分部",
    ])


def _apply_sec_quarter_override(stock_data, base):
    """Override the quarterly headline fields with SEC data when available.
    Falls back to existing values if SEC has no signal."""
    sec_fin = (stock_data or {}).get("sec_financials") or {}
    if not sec_fin.get("available"):
        return
    metrics = sec_fin.get("metrics") or {}
    rev = metrics.get("revenue") or {}
    rev_q = rev.get("latest_q") or {}
    if rev_q.get("val") is not None:
        base["latest_revenue"] = format_currency(rev_q.get("val")) or UNKNOWN_DISPLAY
        change = rev.get("q_yoy_pct")
        if isinstance(change, (int, float)):
            base["revenue_change"] = "{:+.1f}%".format(change)
            base["revenue_change_class"] = "pos" if change > 0 else "neg"
            # core_revenue_growth is the KPI card for Q YoY. Without SEC
            # we never have this; SEC gets it for free.
            base["core_revenue_growth"] = "{:+.1f}%".format(change)
    eps_q = (metrics.get("eps_diluted") or {}).get("latest_q") or {}
    if eps_q.get("val") is not None:
        base["latest_eps"] = "${:.2f}".format(float(eps_q["val"]))
        eps_m = metrics.get("eps_diluted") or {}
        change = eps_m.get("q_yoy_pct")
        if isinstance(change, (int, float)):
            base["eps_change"] = "{:+.1f}%".format(change)
            base["eps_change_class"] = "pos" if change > 0 else "neg"
    rev_v = (rev_q or {}).get("val")
    gp_v = ((metrics.get("gross_profit") or {}).get("latest_q") or {}).get("val")
    if rev_v and gp_v is not None:
        gm = safe_ratio(gp_v, rev_v)
        if gm is not None:
            base["core_gross_margin"] = "{:.2f}%".format(gm)
    rev_prior = ((rev.get("yoy_q") or {}).get("val"))
    gp_prior = (((metrics.get("gross_profit") or {}).get("yoy_q") or {}).get("val"))
    if rev_v and gp_v is not None and rev_prior and gp_prior:
        gm_now = safe_ratio(gp_v, rev_v)
        gm_prior = safe_ratio(gp_prior, rev_prior)
        if gm_now is not None and gm_prior is not None:
            delta_pp = gm_now - gm_prior
            base["margin_change"] = "{:+.0f}".format(delta_pp * 100) if abs(delta_pp) >= 0.005 else "0"
    fcf_label, fcf_val, fcf_scope = _compute_fcf(metrics)
    if fcf_val is not None and fcf_label:
        base["fcf_ttm"] = "{} {}".format(fcf_label, format_currency(fcf_val))
        # FCF yield is a TTM/FY-only ratio — never YTD. We only compute it
        # when SEC gave us a window that actually covers a trailing twelve
        # months or a complete fiscal year; YTD gets `不适用` so the reader
        # doesn't mistake it for the canonical ratio.
        if fcf_scope in ("ttm", "fy"):
            fcf_yield = _compute_fcf_yield(fcf_val, stock_data)
            if fcf_yield is not None:
                base["fcf_yield"] = fcf_yield
        else:
            base["fcf_yield"] = "不适用（YTD 不可计算 FCF Yield）"
    label = sec_fin.get("latest_quarter_label")
    end = sec_fin.get("latest_quarter_end")
    if label and end:
        base["latest_quarter"] = "{}（截至{}，SEC 已披露）".format(label, end)


def _compute_fcf(metrics):
    """Return (label, value_in_dollars, scope) where scope is one of
    ``ttm``, ``fy`` or ``ytd``.

    Only computes ``TTM`` when SEC exposes two consecutive single-quarter
    facts (or one 350-380 day fact). Only computes ``FY`` when the OCF /
    CapEx pair comes from a 10-K filing. Returns ``ytd`` when the only
    available window is a fiscal YTD (e.g. SNDK Q3 10-Q nine-month OCF) —
    this still gives a useful cash-flow number but is NOT a TTM.
    """
    ocf_block = ((metrics.get("operating_cash_flow") or {})
                 .get("ytd") or {})
    capex_block = ((metrics.get("capex") or {})
                   .get("ytd") or {})
    if ocf_block.get("val") is None or capex_block.get("val") is None:
        return None, None, None
    days = _duration_days(ocf_block)
    if days is None:
        return None, None, None
    if 340 <= days <= 380:
        label = "FY"
        scope = "fy"
    elif 180 <= days <= 300:
        label = "YTD"
        scope = "ytd"
    elif 80 <= days <= 100:
        label = "Q"
        scope = "q"
    else:
        # Anything else (stale or partial) — refuse to label as TTM.
        return None, None, None
    return label, float(ocf_block["val"]) - float(capex_block["val"]), scope


def _compute_fcf_yield(fcf_dollars, stock_data):
    """FCF yield is undefined without market cap; bail to None when missing."""
    if fcf_dollars is None:
        return None
    market_cap = stock_data.get("market_cap")
    if market_cap in (None, ""):
        return None
    try:
        mc = float(market_cap)
    except (TypeError, ValueError):
        # Stock-analysis style "$200.6B" / "$1.23T" / "$456M" — strip suffix.
        s = str(market_cap).strip()
        multiplier = 1.0
        if s.endswith("T"):
            multiplier = 1e12
            s = s[:-1]
        elif s.endswith("B"):
            multiplier = 1e9
            s = s[:-1]
        elif s.endswith("M"):
            multiplier = 1e6
            s = s[:-1]
        elif s.endswith("K"):
            multiplier = 1e3
            s = s[:-1]
        s = s.replace("$", "").replace(",", "").strip()
        mc = float(s) * multiplier
    if mc <= 0:
        return None
    return "{:+.2f}%".format(safe_ratio(fcf_dollars, mc))


def _looks_like_already_segmented(html_value):
    """True when the existing field value already contains multiple rows
    that look like genuine segment disclosures — not the synthetic
    placeholder rows the override path produces."""
    if not isinstance(html_value, str):
        return False
    rows = re.findall(r"(?is)<tr[^>]*>.*?</tr>", html_value)
    if len(rows) < 2:
        return False
    joined = re.sub(r"(?s)<[^>]+>", " ", " ".join(rows)).strip()
    if len(joined) < 40:
        return False
    if UNKNOWN_DISPLAY in joined or "未披露/待验证" in joined:
        return False
    return True


def _apply_sec_dashboard_override(base, stock_data):
    """Replace LLM-supplied financial numbers with SEC XBRL outputs whenever
    SEC actually disclosed them.  LLM output is kept untouched for fields the
    extractor could not find, so the report does not regress.  Runs AFTER
    rows_to_html / list_to_li because we want SEC row HTML to win."""
    sec_fin = (stock_data or {}).get("sec_financials") or {}
    if not sec_fin.get("available"):
        return
    company_name = base.get("company_name") or stock_data.get("company_name") or "公司"

    # Headline fields — only fill in what SEC actually has.
    _apply_sec_quarter_override(stock_data, base)

    # Build deterministic tables and overwrite LLM output.
    q_rows, period_label = _build_sec_quarterly_rows(sec_fin)
    if q_rows:
        if normalize_model_row_html("latest_quarter_rows", q_rows) is not None:
            base["latest_quarter_rows"] = q_rows
    if period_label and base.get("latest_quarter") in (None, "", UNKNOWN_DISPLAY):
        base["latest_quarter"] = period_label
    fy_rows = _build_sec_fy_rows(sec_fin)
    if fy_rows and normalize_model_row_html("fy_comparison_rows", fy_rows) is not None:
        base["fy_comparison_rows"] = fy_rows
    bs_rows = _build_sec_balance_sheet_rows(sec_fin)
    if bs_rows and normalize_model_row_html("balance_sheet_rows", bs_rows) is not None:
        base["balance_sheet_rows"] = bs_rows

    # Business rows: do not override when the LLM already produced a
    # multi-row layout backed by a 10-K Note. The override path
    # only steps in when the existing row is single-or-empty AND no
    # genuine segment axis exists in XBRL — see _build_sec_business_rows
    # for the conservative single-row branch.
    if _looks_like_already_segmented(base.get("business_rows")):
        pass
    else:
        biz_rows = _build_sec_business_rows(sec_fin, company_name)
        if biz_rows and normalize_model_row_html(
                "business_rows", biz_rows) is not None:
            base["business_rows"] = biz_rows

    # segment_rows: same defensive approach — only override when the LLM
    # left a single-row placeholder. Multi-row layouts survive.
    if _looks_like_already_segmented(base.get("segment_rows")):
        pass
    else:
        rev_q = ((sec_fin.get("metrics", {}).get("revenue") or {})
                 .get("latest_q") or {})
        rev_yoy_pct = ((sec_fin.get("metrics", {}).get("revenue") or {})
                       .get("q_yoy_pct"))
        yoy_cell = "{:+.1f}%".format(rev_yoy_pct) if isinstance(
            rev_yoy_pct, (int, float)) else MISSING_NOT_DISCLOSED
        seg_html = _row_html([
            company_name + " 合并口径（非分部数据）",
            format_currency(rev_q.get("val")) or UNKNOWN_DISPLAY,
            "不适用",
            yoy_cell,
            MISSING_TO_CROSS_VERIFY,
            "SEC XBRL 未提供 Segment 轴；产品族见 product_rows",
        ])
        if normalize_model_row_html("segment_rows", seg_html) is not None:
            base["segment_rows"] = seg_html

    # Note SEC filing dates in data_sources so reviewers can audit quickly.
    if sec_fin.get("as_of_filed") and sec_fin.get("source_url"):
        existing_sources = base.get("data_sources")
        if isinstance(existing_sources, str):
            # list_to_li has already converted this to an HTML string. Strip
            # the wrapper so we can append cleanly, then re-render at the end.
            existing_sources = _li_to_list(existing_sources)
        if not isinstance(existing_sources, list):
            existing_sources = []
        existing_sources.append(
            "SEC XBRL companyfacts @ {} ({})".format(
                sec_fin["as_of_filed"], sec_fin["source_url"]),
        )
        base["data_sources"] = existing_sources


def _li_to_list(html_value):
    """Reverse-engineer an HTML <li>...</li> blob back into a list of strings."""
    if not isinstance(html_value, str):
        return html_value
    text = re.sub(r"(?is)<[^>]+>", " ", html_value)
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        parts = [p.strip() for p in re.split(r"[·|]", text) if p.strip()]
    return parts or [text.strip()]


# Per-column semantic label mapping.  Empty cells in column N inside a row use
# the label mapped from the *header* column name.  This keeps row upgrades
# scoped: we never replace content we can't classify (e.g. values that came
# from research_sources).
_ROW_COLUMN_LABELS = {
    "YoY": "不适用",
    "同比": "不适用",
    "5y中位数": "历史不足",
    "5y 中位数": "历史不足",
    "5y median": "历史不足",
    "vs预期": "不适用",
    "vs 预期": "不适用",
    "评价": "未单独披露（来源缺口）",
    "Net Income": "公司未单独披露",
    "战略作用": "公司未单独披露",
    "业务意义": "公司未单独披露",
    "环比": "公司未单独披露",
    "Q/Q": "公司未单独披露",
    "占比": "100%",
    "YoY 变化": "不适用",
}


def _upgrade_row_cells(html_rows, row_field=None, fallback_label=UNKNOWN_DISPLAY):
    """Replace each `<td>未披露 / 待验证</td>` cell with the column-specific
    label. Header comes from ``row_field`` in ROW_SCHEMAS since the template
    renders the header outside the field value."""
    if not isinstance(html_rows, str):
        return html_rows
    header_cells = list(ROW_SCHEMAS.get(row_field, ()) if row_field else ())
    if not header_cells:
        # Fall back to first <tr> <th> if present
        header_match = re.search(r"(?is)<tr[^>]*>(.*?)</tr>", html_rows)
        if header_match:
            header_cells = re.findall(
                r"(?is)<th[^>]*>(.*?)</th>", header_match.group(1))
    if not header_cells:
        return html_rows
    unknown_patterns = (UNKNOWN_DISPLAY, "未披露/待验证")

    def repl(match):
        # Restrict column counting to the current <tr> only — counting
        # across the entire prefix was producing wrong indices for cells in
        # later rows.
        prefix = html_rows[:match.start()]
        last_tr = prefix.rfind("<tr")
        if last_tr < 0:
            return match.group(0)
        row_prefix = prefix[last_tr:]
        col_index = len(re.findall(r"(?is)<td[^>]*>", row_prefix))
        if col_index >= len(header_cells):
            return match.group(0)
        header = re.sub(r"(?s)<[^>]+>", "", header_cells[col_index]).strip()
        label = _ROW_COLUMN_LABELS.get(header, fallback_label)
        return "<td>{}</td>".format(html_escape(label))

    cell_regex = r"(?is)<td[^>]*>\s*(?:{})(?:[^<]*)\s*</td>".format(
        "|".join(re.escape(p) for p in unknown_patterns))
    return re.sub(cell_regex, repl, html_rows)


def _finalize_missing_fields(base):
    """Fill remaining empty placeholders with differentiated missing-state
    labels instead of the blanket `未披露 / 待验证` default."""
    known_labels = {field: label for field, label, _ in MISSING_STATE_TABLE}
    is_recent_spinoff = _is_recent_spinoff(
        (base.get("analysis_timestamp") or "")[:10])
    for field in template_placeholders():
        if base.get(field) not in (None, "", [], {}):
            continue
        if field in known_labels:
            base[field] = known_labels[field]
            continue
        base[field] = _classify_missing(field, base, is_recent_spinoff)


def _refine_existing_unknowns(base):
    """Convert blanket `未披露 / 待验证` strings into field-specific missing
    labels when we know the reason (FMP 402, history <5y, etc.).

    Runs late so it does not fight the SEC override path; it only rewrites
    placeholders the LLM originally filled with the generic phrase.
    """
    known_labels = {field: label for field, label, _ in MISSING_STATE_TABLE}
    is_recent_spinoff = _is_recent_spinoff(
        (base.get("analysis_timestamp") or "")[:10])
    for field in template_placeholders():
        value = base.get(field)
        if not isinstance(value, str):
            continue
        # Recovery: ROW_FIELDS that got wholesale-collapsed to a single label
        # in an earlier rerender need their full row shape restored, otherwise
        # the template renders a one-cell table that fails the schema check.
        is_row_value = bool(re.search(r"(?is)<tr[^>]*>", value))
        if field in ROW_FIELDS and not is_row_value:
            label = known_labels.get(field, "待交叉验证")
            cols = ROW_SCHEMAS[field]
            base[field] = _row_html([label] * len(cols))
            continue
        if UNKNOWN_DISPLAY not in value and "未披露/待验证" not in value:
            continue
        name = field.lower()
        if is_row_value:
            # Specific cells inside rows are still lifted to specific labels
            # when we know the row-level intent (e.g. customer_rows, eps_change,
            # revenue_change, segment/fy comparisons). Keep substitutions
            # scoped to known unstable fields.
            if field in known_labels and field not in ROW_FIELDS:
                continue  # leave row-containing value alone
            if field in ROW_FIELDS:
                base[field] = _upgrade_row_cells(
                    value, row_field=field,
                    fallback_label=MISSING_TO_CROSS_VERIFY)
            continue

        if field in known_labels:
            # For row-shaped values, swap the unknown phrase *inside* every
            # <td>...</td> cell — never the whole row.
            if field in ROW_FIELDS:
                base[field] = _upgrade_row_cells(
                    value, row_field=field,
                    fallback_label=known_labels[field])
                continue
            base[field] = known_labels[field]
            continue

        if name.startswith("verify_") or name.startswith("winner_"):
            base[field] = re.sub(re.escape(UNKNOWN_DISPLAY),
                                 MISSING_TO_CROSS_VERIFY, value)
            continue
        if name in ("net_debt", "enterprise_value", "forward_pe", "ev_sales"):
            base[field] = re.sub(re.escape(UNKNOWN_DISPLAY),
                                 MISSING_SOURCE_UNAVAILABLE, value)
            continue
        if is_recent_spinoff and any(t in name for t in
                                     ("median", "history", "ytd", "5y")):
            base[field] = re.sub(re.escape(UNKNOWN_DISPLAY),
                                 MISSING_INSUFFICIENT_HISTORY, value)
            continue
        if name == "price_implication":
            base[field] = re.sub(re.escape(UNKNOWN_DISPLAY),
                                 "数据源暂不可用（依赖分析师模型）", value)
            continue


MISSING_STATE_TABLE = (
    ("pe_median", MISSING_INSUFFICIENT_HISTORY, ""),
    ("ytd_return", MISSING_INSUFFICIENT_HISTORY, ""),
    ("week52_low", MISSING_INSUFFICIENT_HISTORY, ""),
    ("week52_high", MISSING_INSUFFICIENT_HISTORY, ""),
    ("forward_pe", MISSING_SOURCE_UNAVAILABLE, ""),
    ("forward_ev_sales", MISSING_SOURCE_UNAVAILABLE, ""),
    ("ev_sales", MISSING_SOURCE_UNAVAILABLE, ""),
    ("eps_change", MISSING_NOT_DISCLOSED, ""),
    ("eps_change_class", "warn", ""),
    ("revenue_change", MISSING_NOT_DISCLOSED, ""),
    ("revenue_change_class", "warn", ""),
    ("customer_rows", "公司未单独披露（10-Q Note 表格需人工核读）", ""),
    ("comp_direct", UNKNOWN_DISPLAY, ""),
    ("comp_indirect", UNKNOWN_DISPLAY, ""),
    ("comp_substitute", UNKNOWN_DISPLAY, ""),
    ("comp_insourcing", UNKNOWN_DISPLAY, ""),
)


def _classify_missing(field, base, is_recent_spinoff):
    """Best-effort label for empty placeholders we did not specifically map."""
    name = (field or "").lower()
    if "product_split" in name or "segment" in name or "business_split" in name:
        return MISSING_NOT_DISCLOSED
    if any(token in name for token in ("forward_", "ev_sales", "ev_ebitda")):
        return MISSING_SOURCE_UNAVAILABLE
    if any(token in name for token in ("5y", "median", "ytd", "history")):
        return MISSING_INSUFFICIENT_HISTORY if is_recent_spinoff else UNKNOWN_DISPLAY
    if "guidance" in name or "next_earnings" in name:
        return MISSING_TO_CROSS_VERIFY
    if "verify_" in name:
        return MISSING_NOT_DISCLOSED
    return UNKNOWN_DISPLAY


def normalize_dashboard_data(ticker, stock_data, obj, reason=None):
    fields = template_placeholders()
    base = default_dashboard(ticker, stock_data, reason or "fallback")
    data = obj.get("dashboard_data", obj) if isinstance(obj, dict) else {}
    if not isinstance(data, dict):
        data = {}
    base.update(data)
    base["TICKER"] = ticker
    base["current_date"] = time.strftime("%Y-%m-%d")
    base["analysis_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for source_key, target_key in (
        ("company_name", "company_name"), ("exchange", "exchange"), ("industry", "industry"),
        ("price", "current_price"), ("fwd_pe", "forward_pe"),
        ("wk52_high", "week52_high"), ("wk52_low", "week52_low"),
        ("price_change", "price_change"), ("price_change_pct", "price_change_pct"),
    ):
        if stock_data.get(source_key) not in (None, ""):
            base[target_key] = str(stock_data[source_key])
    if stock_data.get("market_cap") not in (None, ""):
        market_cap = stock_data["market_cap"]
        try:
            market_cap_number = float(market_cap)
            if market_cap_number >= 1e12:
                market_cap = "${:.2f}T".format(market_cap_number / 1e12)
            elif market_cap_number >= 1e9:
                market_cap = "${:.2f}B".format(market_cap_number / 1e9)
            elif market_cap_number >= 1e6:
                market_cap = "${:.2f}M".format(market_cap_number / 1e6)
        except (TypeError, ValueError):
            pass
        base["market_cap"] = str(market_cap)
    try:
        change = float(stock_data.get("price_change"))
        base["price_change"] = "{:+.2f}".format(change)
        base["price_change_symbol"] = "▲" if change > 0 else "▼" if change < 0 else ""
        base["price_change_class"] = "pos" if change > 0 else "neg" if change < 0 else ""
    except (TypeError, ValueError):
        pass
    try:
        base["price_change_pct"] = "{:+.2f}%".format(float(stock_data.get("price_change_pct")))
    except (TypeError, ValueError):
        pass
    compact_dashboard_display(base)
    remove_prohibited_advice(base)
    for field in LIST_FIELDS:
        base[field] = list_to_li(base.get(field))
    for field in ROW_FIELDS:
        base[field] = rows_to_html(base.get(field))
    _apply_sec_dashboard_override(base, stock_data)
    _refine_existing_unknowns(base)
    _finalize_missing_fields(base)
    return base


def normalize_analysis(data):
    """Test alias: takes data dict, returns normalized defaults."""
    ticker = (data or {}).get("TICKER", "X")
    obj = {"dashboard_data": data or {}}
    return normalize_dashboard_data(ticker, {}, obj, reason=(data or {}).get("__reason__"))



def check_compliance(data):
    issues = []
    for field in template_placeholders():
        if data.get(field) in (None, "", [], {}):
            issues.append(f"Missing placeholder: {field}")
    text = json.dumps(data, ensure_ascii=False)
    for bad in ("某某等", "等等", "其他等", "其他等等"):
        if bad in text:
            issues.append(f"Prohibited lazy text: {bad}")
    for bad in ("快速版未覆盖", "需要按 skill 补充", "待生成"):
        if bad in text:
            issues.append("Incomplete research marker: " + bad)
    for bad in ("模型记忆", "行业常识"):
        if bad in text:
            issues.append("Unsupported evidence source: " + bad)
    for bad in PROHIBITED_ADVICE_TERMS:
        if bad.lower() in text.lower():
            issues.append("Prohibited investment advice: " + bad)
    for field in ROW_SCHEMAS:
        if normalize_model_row_html(field, data.get(field)) is None:
            issues.append("Invalid row schema: " + field)
    today = time.strftime("%Y-%m-%d")
    if data.get("current_date") != today:
        issues.append(f"Stale current_date: {data.get('current_date')}")
    if not str(data.get("analysis_timestamp", "")).startswith(today):
        issues.append(f"Stale analysis_timestamp: {data.get('analysis_timestamp')}")
    required_phrases = ["概览", "财务估值", "产业链", "竞对", "客户验证", "周期催化", "监控"]
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    for phrase in required_phrases:
        if phrase not in template:
            issues.append(f"Template missing tab: {phrase}")
    return issues


def text_from_html(value):
    text = re.sub(r"(?i)</(?:p|li|tr|h[1-6])>", "\n", str(value or ""))
    text = re.sub(r"(?i)<td[^>]*>", " | ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(" |\n")


def render_markdown_report(ticker, data):
    sections = [
        ("一句话结论", data.get("one_liner")),
        ("公司是什么", data.get("company_definition")),
        ("投资逻辑与价格隐含", "{}\n\n{}".format(data.get("investment_thesis", ""), data.get("price_implication", ""))),
        ("最新财务与估值", "{}\n\n{}\n\n{}".format(data.get("latest_quarter_rows", ""), data.get("valuation_rows", ""), data.get("balance_sheet_rows", ""))),
        ("业务与产品", "{}\n\n{}\n\n{}".format(data.get("business_rows", ""), data.get("business_summary", ""), data.get("product_rows", ""))),
        ("产业链位置", "{}\n\n{}".format(data.get("industry_chain_classification", ""), data.get("chain_rows", ""))),
        ("竞争格局", "{}\n\n{}".format(data.get("comp_financial_rows", ""), data.get("product_difference", ""))),
        ("客户验证", "{}\n\n{}".format(data.get("customer_rows", ""), data.get("customer_risk", ""))),
        ("周期与催化剂", "{}\n\n{}".format(data.get("catalyst_rows", ""), data.get("cycle_key_judgment", ""))),
        ("监控清单", "{}\n\n{}\n\n{}".format(data.get("monitoring_metrics", ""), data.get("invalidation_conditions", ""), data.get("sell_conditions", ""))),
        ("数据来源与冲突", "{}\n\n{}".format(data.get("data_sources", ""), data.get("data_conflicts", ""))),
    ]
    parts = ["# {} — 公司研究".format(ticker), ""]
    for heading, content in sections:
        parts.extend(["## " + heading, text_from_html(content), ""])
    return "\n".join(parts).strip() + "\n"


def render_html(ticker, data, sample=None, output_file=None):
    """Compliance test alias: ticker, data dict, sample analysis dict."""
    merged = data.copy() if isinstance(data, dict) else {}
    if isinstance(sample, dict):
        merged.update(sample)
    if output_file is None:
        output_file = "/tmp/_r_test.html"
    return render_dashboard(merged, output_file)


def render_dashboard(data, output_file):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    def repl(m):
        return str(data.get(m.group(1), ""))
    html = re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", repl, template)
    Path(output_file).write_text(html, encoding="utf-8")
    return html


def trigger(ticker, force=False):
    ticker = re.sub(r"[^A-Za-z0-9._-]", "", ticker.upper())
    if not ticker:
        raise ValueError("empty ticker")
    today = time.strftime("%Y-%m-%d")
    os.makedirs(DASH_DIR, exist_ok=True)
    output_file = os.path.join(DASH_DIR, f"{ticker}-{today}.html")
    md_file = os.path.join(DASH_DIR, f"{ticker}-{today}.md")
    json_file = os.path.join(DASH_DIR, f"{ticker}-{today}.json")
    if os.path.isfile(output_file) and not force:
        return output_file, "exists"
    stock_data = fetch_stock_data(ticker)
    obj, err = call_llm(ticker, stock_data, load_env(DSA_ENV_PATH))
    if err or not isinstance(obj, dict):
        raise RuntimeError("ER LLM output unusable: {}".format(err or "missing JSON object"))
    data = normalize_dashboard_data(ticker, stock_data, obj, err)
    issues = check_compliance(data)
    fatal_issues = [
        issue for issue in issues
        if issue.startswith("Missing placeholder:")
        or issue.startswith("Incomplete research marker:")
        or issue.startswith("Unsupported evidence source:")
        or issue.startswith("Invalid row schema:")
        or issue.startswith("Prohibited investment advice:")
    ]
    if fatal_issues:
        raise RuntimeError("ER full-skill quality gate failed: " + "; ".join(fatal_issues[:12]))
    render_dashboard(data, output_file)
    md = render_markdown_report(ticker, data)
    Path(md_file).write_text(md, encoding="utf-8")
    Path(json_file).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    status = f"generated,compliance:{len(issues)}"
    if err:
        status += f",llm_error:{err[:120]}"
    if issues:
        sys.stderr.write("\n".join(issues[:10]) + "\n")
    return output_file, status


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: trigger.py TICKER [--force]")
        sys.exit(1)
    out, status = trigger(sys.argv[1], "--force" in sys.argv[2:])
    print(f"{status}: {out}")
