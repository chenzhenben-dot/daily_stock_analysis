#!/usr/bin/env python3
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DSA_ENV_PATH = "/opt/dsa/.env"
DASH_DIR = "/opt/er-dashboards"
LOCAL_SKILL_DIR = Path.home() / ".claude/skills/equity-research"
SERVER_SKILL_DIR = Path("/opt/er-dashboard/equity-research")
SKILL_DIR = SERVER_SKILL_DIR if (SERVER_SKILL_DIR / "SKILL.md").exists() else LOCAL_SKILL_DIR
SKILL_PATH = SKILL_DIR / "SKILL.md"
TEMPLATE_PATH = SKILL_DIR / "references/dashboard-template.html"
GENERATOR_PATH = SKILL_DIR / "references/dashboard-generator.py"

ACTION_MAP = {
    "可以买/加仓": ("buy", "可以买/加仓"), "买入": ("buy", "可以买/加仓"), "buy": ("buy", "可以买/加仓"), "add": ("buy", "可以买/加仓"),
    "持有": ("hold", "持有"), "hold": ("hold", "持有"),
    "等待回调": ("wait", "等待回调"), "wait": ("wait", "等待回调"),
    "小仓试错": ("try", "小仓试错"), "try": ("try", "小仓试错"),
    "减仓": ("reduce", "减仓"), "reduce": ("reduce", "减仓"),
    "卖出": ("sell", "卖出"), "sell": ("sell", "卖出"),
    "回避": ("avoid", "回避"), "avoid": ("avoid", "回避"),
    "观察名单": ("watch", "观察名单"), "观察": ("watch", "观察名单"), "watch": ("watch", "观察名单"),
}
LIST_FIELDS = {"monitoring_metrics", "product_milestones", "valuation_assumptions", "invalidation_conditions", "sell_conditions", "data_conflicts", "data_sources"}
ROW_FIELDS = {"latest_quarter_rows", "fy_comparison_rows", "segment_rows", "guidance_rows", "valuation_rows", "balance_sheet_rows", "comp_financial_rows", "customer_rows", "catalyst_rows", "business_rows", "product_rows", "chain_rows"}
CLASS_FIELDS = {"action_class", "conclusion_class", "price_change_class", "ytd_class", "revenue_change_class", "eps_change_class", "business_cycle_class", "price_cycle_class", "risk_self_class", "risk_substitute_class", "risk_geo_class", "risk_cycle_class", "verify_paid_class", "verify_repeat_class", "verify_production_class", "verify_concentration_class", "verify_source_class"}

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
        "sell_conditions", "data_conflicts", "data_sources", "action_class", "action_label", "action_rationale",
        "conclusion_class", "one_liner", "investment_thesis", "price_implication",
    ]),
]


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
    "phase_4_action": "buy | add | hold | wait | try | reduce | sell | avoid | watch",
    "phase_4_rationale": "action rationale with quality gating",
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

VALID_ACTIONS = {"buy", "add", "hold", "wait", "try", "reduce", "sell", "avoid", "watch"}

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


def fetch_url(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ER-AutoGen/1.0 research dashboard contact: no-reply@example.com",
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
            wanted = {
                "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss", "EarningsPerShareDiluted",
                "Assets", "Liabilities", "CashAndCashEquivalentsAtCarryingValue", "LongTermDebt",
                "StockholdersEquity", "NetCashProvidedByUsedInOperatingActivities",
                "PaymentsToAcquirePropertyPlantAndEquipment", "CommonStockSharesOutstanding",
            }
            fact_rows = []
            for taxonomy in ("us-gaap", "ifrs-full"):
                for tag, fact in facts_payload.get("facts", {}).get(taxonomy, {}).items():
                    if tag not in wanted:
                        continue
                    entries = []
                    for unit_rows in fact.get("units", {}).values():
                        entries.extend(unit_rows)
                    entries = [row for row in entries if row.get("form") in ("10-K", "10-Q", "20-F", "6-K")]
                    entries.sort(key=lambda row: (row.get("filed", ""), row.get("end", "")), reverse=True)
                    if entries:
                        fact_rows.append({
                            "tag": tag,
                            "label": fact.get("label", tag),
                            "recent": entries[:8],
                        })
            out.setdefault("research_sources", []).append({
                "name": "sec_companyfacts",
                "url": facts_url,
                "text": json.dumps(fact_rows, ensure_ascii=False)[:24000],
            })
        except Exception as exc:
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
                    ("exchange", "exchange"), ("industry", "industry"),
                ):
                    if profile.get(source_key) not in (None, ""):
                        out[target_key] = profile[source_key]
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
        "action_class": "watch", "action_label": "观察名单", "action_rationale": reason,
        "conclusion_class": "warn", "one_liner": f"{ticker} 已进入 ER skill 深度尽调流程；当前数据不足，先列观察名单。",
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
    today = time.strftime("%Y-%m-%d")
    analysis_timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    skill = SKILL_PATH.read_text(encoding="utf-8")
    if not all(x in skill for x in ("Phase 1：定问题", "Phase 2：研究层", "Phase 3：动作层", "Phase 5：监控清单", "Hard rules")):
        raise RuntimeError("equity-research SKILL.md missing required sections")
    skill_digest = """
你是 equity-research 完整工作流中的单阶段执行器。程序会按顺序分别完成公司概览、财务估值、业务产业链、竞对客户、周期行动监控五个阶段；你只完成当前阶段和当前字段,不要重新规划整套报告,不要输出提纲。
研究纪律:
1. 数字只用提供的来源,必须保留日期和口径；找不到写“未披露 / 待验证”,禁止猜测。
2. 公司一手披露/SEC > FMP/Alpha Vantage/StockAnalysis > 搜索摘要 > 模型记忆。
3. 单源结论标“待交叉验证”；数据冲突要列明,不强行选一个。
4. 不写“某某等/等等/其他等”；产品、客户、业务尽量列全。
5. 先判断真实产业链,不默认套 AI；技术面只用于择时。
6. 输出应是可直接发布的正式看板内容,不是“待补充”的骨架。
7. 直接完成字段并返回 JSON；无需展示思考过程。
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

JSON 格式:
{{"dashboard_data":{{...全部模板字段...}},"brief_summary":"300字以内总结","compliance_notes":["待交叉验证/未披露说明"]}}

字段规则:
- *_rows 字段输出 HTML <tr><td>...</td></tr> 字符串。
- monitoring_metrics/product_milestones/valuation_assumptions/invalidation_conditions/sell_conditions/data_conflicts/data_sources 输出 list。
- action_class 只能是 buy/hold/wait/try/reduce/sell/avoid/watch。
- class 字段用 pos/neg/warn 或 action class。
- 必须真正完成当前阶段的研究和解释,不是生成提纲或索引。未找到的数据写“未披露 / 待验证”,不能编造。
- 禁止输出“快速版未覆盖”“需要按 skill 补充”“待生成”。如果来源不足,要说明查过哪些来源及缺口。
- 内容质量要接近正式 ER 看板,像 GLW 示例那样有业务、产品、产业链、竞对、客户验证、催化剂和监控。
- current_date 必须等于 {today}; analysis_timestamp 必须等于 {analysis_timestamp}。禁止输出历史分析时间。
- 不要复用旧报告、旧结论或旧页脚；如果某个最新财报/价格/估值数据无法核验,标注“未披露 / 待验证”并说明数据源缺口。
- 优先使用 high-priority JSON 里的 research_sources；公司 IR/SEC 正文、FMP、StockAnalysis 和最新搜索结果高于模型记忆。
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
            return None, "unbalanced JSON object in model content", content
        try:
            return json.loads(content[start:end]), None, content
        except Exception as parse_err:
            return None, "JSON parse failed: " + str(parse_err)[:160], content

    def request_json(prompt, max_tokens, timeout=180):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是严格执行 Claude SKILL.md 的股票研究助手。只输出完整闭合 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "reasoning_split": True,
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
        chunks = [fields[index:index + 12] for index in range(0, len(fields), 12)]
        for chunk_index, chunk in enumerate(chunks, 1):
            print("ER_BATCH {}/{} {} {}/{}".format(stage_index, total_stages, stage_name, chunk_index, len(chunks)), flush=True)
            prompt_data = trim_stock_data_for_prompt(stock_data, per_source_limit=900, max_sources=24)
            if merged["dashboard_data"]:
                prompt_data["completed_stage_data"] = merged["dashboard_data"]
            try:
                prompt = build_prompt(
                    ticker,
                    prompt_data,
                    compact=False,
                    fields_override=chunk,
                    stage_name="{} ({}/{})".format(stage_name, chunk_index, len(chunks)),
                )
                obj, err, raw_content = request_json(prompt, max_tokens=9000, timeout=300)
                if err:
                    Path("/tmp/er-llm-last.txt").write_text(raw_content[:20000], encoding="utf-8")
                    return None, "{} batch {}/{} JSON failed: {}".format(stage_name, chunk_index, len(chunks), err)
                data = obj.get("dashboard_data", obj) if isinstance(obj, dict) else {}
                if not isinstance(data, dict):
                    return None, "{} batch {}/{} missing dashboard_data".format(stage_name, chunk_index, len(chunks))
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
                        data.update(retry_values)
                    missing = [field for field in chunk if data.get(field) in (None, "", [], {})]
                    if missing:
                        return None, "{} still missing fields: {}".format(stage_name, ",".join(missing))
                merged["dashboard_data"].update({field: data[field] for field in chunk})
            except urllib.error.HTTPError as e:
                return None, "{} HTTP {}: {}".format(stage_name, e.code, e.read().decode("utf-8", errors="ignore")[:300])
            except Exception as e:
                return None, "{} request failed: {}".format(stage_name, str(e)[:300])
    return merged, None


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
    action_class, action_label = ACTION_MAP.get(str(base.get("action_class") or base.get("action_label") or "watch"), ("watch", "观察名单"))
    base["action_class"] = action_class
    base["action_label"] = base.get("action_label") if base.get("action_label") not in ("", None, "未披露 / 待验证") else action_label
    for field in LIST_FIELDS:
        base[field] = list_to_li(base.get(field))
    for field in ROW_FIELDS:
        base[field] = rows_to_html(base.get(field))
    for field in fields:
        if base.get(field) in (None, "", [], {}):
            base[field] = "未披露 / 待验证"
    return base


def normalize_analysis(data):
    """Test alias: takes data dict, returns normalized defaults."""
    ticker = (data or {}).get("TICKER", "X")
    obj = {"dashboard_data": data or {}}
    return normalize_dashboard_data(ticker, {}, obj, reason=(data or {}).get("__reason__"))



def enforce_action_gate(data):
    """v2 §10.6: action quality gating."""
    a_pct = data.get("a_pct")
    if a_pct is None:
        a_pct = (data.get("phase_5_monitoring", {}).get("data_quality", {}) or {}).get("a_pct")
    current = data.get("action") or data.get("action_class", "watch")
    if a_pct is None:
        return current, None
    if a_pct >= 70:
        return current, None
    elif a_pct >= 30:
        if current in ("buy", "add"):
            return "try", "Quality %s%% A: buy->try" % a_pct
        return current, None
    else:
        if current not in ("watch", "avoid", "reduce", "sell"):
            return "watch", "Quality %s%% A: force watch" % a_pct
        return current, None


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
    parts = ["# {} — {}".format(ticker, data.get("action_label", "观察名单")), ""]
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
    if os.path.isfile(output_file) and not force:
        return output_file, "exists"
    stock_data = fetch_stock_data(ticker)
    obj, err = call_llm(ticker, stock_data, load_env(DSA_ENV_PATH))
    if err or not isinstance(obj, dict):
        raise RuntimeError("ER LLM output unusable: {}".format(err or "missing JSON object"))
    data = normalize_dashboard_data(ticker, stock_data, obj, err)
    data["action_class"], action_note = enforce_action_gate(data)
    if action_note:
        data["action_rationale"] = (data.get("action_rationale", "") or "") + " | " + action_note
    issues = check_compliance(data)
    fatal_issues = [issue for issue in issues if issue.startswith("Missing placeholder:") or issue.startswith("Incomplete research marker:")]
    if fatal_issues:
        raise RuntimeError("ER full-skill quality gate failed: " + "; ".join(fatal_issues[:12]))
    render_dashboard(data, output_file)
    md = render_markdown_report(ticker, data)
    Path(md_file).write_text(md, encoding="utf-8")
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
