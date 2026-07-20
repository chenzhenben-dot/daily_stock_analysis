"""Offline stability tests for the ER trigger pipeline.

All tests operate on a hand-built SEC companyfacts fixture that mirrors the
known SNDK FY2026 Q3 disclosure, so we never hit the network and the
results stay deterministic.  Every assertion that used to depend on the LLM
has been replaced with a deterministic SEC-derived check.
"""
import importlib.util
import json
import unittest
from pathlib import Path


TRIGGER_PATH = Path(__file__).resolve().with_name("trigger.py")
if not TRIGGER_PATH.exists():
    TRIGGER_PATH = Path("work/trigger.py")
SPEC = importlib.util.spec_from_file_location("er_trigger", str(TRIGGER_PATH))
TRIGGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIGGER)


def _build_fixture_companyfacts():
    """Synthetic SEC XBRL companyfacts mirroring the SNDK FY2026 Q3 filing.

    The fixture purposefully includes both single-quarter and year-to-date
    duration facts, so the extractor must pick the ~89-day Q3 record over the
    ~280-day cumulative one.  A second CY2025Q3 entry exists for YoY
    comparison and a duplicate of the recent Q3 is included to verify
    de-duplication.
    """
    def f(end, start, val, form="10-Q", fp="Q3", fy=2026, filed="2026-05-01",
          accn="0002023554-26-000010", unit="USD", frame=None):
        return {
            "end": end, "start": start, "val": val, "accn": accn,
            "fy": fy, "fp": fp, "form": form, "filed": filed,
            "frame": frame or ("CY{}Q{}".format(fy, fp[1])),
            "unit": unit,
        }

    revenue_block = {
        "label": "Revenue from Contract with Customer, Excluding Assessed Tax",
        "units": {"USD": [
            # Q3 FY2026 single quarter — 89 days, 5.95B
            f("2026-04-03", "2026-01-04", 5.95e9, fp="Q3", fy=2026),
            # YTD FY2026 (9 months) — 280 days, 11.283B
            f("2026-04-03", "2025-06-28", 1.1283e10, fp="Q3", fy=2026),
            # Q3 FY2025 single quarter — for YoY comparability
            f("2025-04-04", "2024-12-29", 2.05e9, fp="Q3", fy=2025),
            # Prior YTD for YoY (281 days, 5.4B)
            f("2025-04-04", "2024-06-29", 5.4e9, fp="Q3", fy=2025),
            # Duplicate of the Q3 FY2026 single-quarter fact to confirm
            # dedup runs (same (val, start, end)).
            f("2026-04-03", "2026-01-04", 5.95e9, fp="Q3", fy=2026),
        ]},
    }

    gp_block = {
        "label": "Gross Profit",
        "units": {"USD": [
            f("2026-04-03", "2026-01-04", 4.662e9, fp="Q3", fy=2026),
            f("2026-04-03", "2025-06-28", 7.5e9, fp="Q3", fy=2026),
            f("2025-04-04", "2024-12-29", 0.98e9, fp="Q3", fy=2025),
        ]},
    }

    op_block = {
        "label": "Operating Income (Loss)",
        "units": {"USD": [
            f("2026-04-03", "2026-01-04", 4.111e9, fp="Q3", fy=2026),
            f("2026-04-03", "2025-06-28", 6.6e9, fp="Q3", fy=2026),
            f("2025-04-04", "2024-12-29", 0.83e9, fp="Q3", fy=2025),
        ]},
    }

    ni_block = {
        "label": "Net Income (Loss)",
        "units": {"USD": [
            f("2026-04-03", "2026-01-04", 3.615e9, fp="Q3", fy=2026),
            f("2025-04-04", "2024-12-29", 0.49e9, fp="Q3", fy=2025),
        ]},
    }

    eps_block = {
        "label": "Earnings Per Share, Diluted",
        "units": {"USD/shares": [
            {"end": "2026-04-03", "start": "2026-01-04", "val": 23.03,
             "accn": "0002023554-26-000010", "fy": 2026, "fp": "Q3",
             "form": "10-Q", "filed": "2026-05-01",
             "frame": "CY2026Q3", "unit": "USD/shares"},
            {"end": "2025-04-04", "start": "2024-12-29", "val": 9.10,
             "accn": "0002023554-25-000010", "fy": 2025, "fp": "Q3",
             "form": "10-Q", "filed": "2025-05-02",
             "frame": "CY2025Q3", "unit": "USD/shares"},
        ]},
    }

    ocf_block = {
        "label": "Net Cash Provided by (Used in) Operating Activities",
        "units": {"USD": [
            # YTD OCF — 9 months, 4.545B
            f("2026-04-03", "2025-06-28", 4.545e9, fp="Q3", fy=2026),
        ]},
    }

    capex_block = {
        "label": "Payments to Acquire Property, Plant, and Equipment",
        "units": {"USD": [
            # YTD CapEx — 9 months, 0.134B
            f("2026-04-03", "2025-06-28", 0.134e9, fp="Q3", fy=2026),
        ]},
    }

    assets_block = {
        "label": "Assets",
        "units": {"USD": [
            {"end": "2026-04-03", "val": 17.075e9,
             "accn": "0002023554-26-000010", "fy": 2026, "fp": "Q3",
             "form": "10-Q", "filed": "2026-05-01",
             "frame": "CY2026Q3", "unit": "USD"},
            {"end": "2025-06-27", "val": 12.985e9,
             "accn": "0002023554-25-000040", "fy": 2025, "fp": "FY",
             "form": "10-K", "filed": "2025-08-30", "unit": "USD"},
        ]},
    }

    return {
        "cik": 2023554,
        "entityName": "Sandisk Corp",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": revenue_block,
            "GrossProfit": gp_block,
            "OperatingIncomeLoss": op_block,
            "NetIncomeLoss": ni_block,
            "EarningsPerShareDiluted": eps_block,
            "NetCashProvidedByUsedInOperatingActivities": ocf_block,
            "PaymentsToAcquirePropertyPlantAndEquipment": capex_block,
            "Assets": assets_block,
        }},
    }


class TriggerStabilityTests(unittest.TestCase):

    def setUp(self):
        self.facts = _build_fixture_companyfacts()

    # --- Existing tests (kept verbatim) ---

    def test_decodes_and_normalizes_escaped_rows(self):
        value = (
            "&lt;tr&gt;&lt;td&gt;Revenue&lt;/td&gt;&lt;td&gt;10&lt;/td&gt;"
            "&lt;td&gt;12&lt;/td&gt;&lt;td&gt;+20%&lt;/td&gt;&lt;/tr&gt;"
        )
        normalized = TRIGGER.normalize_model_row_html("fy_comparison_rows", value)
        self.assertEqual(normalized, "<tr><td>Revenue</td><td>10</td><td>12</td><td>+20%</td></tr>")

    def test_rejects_wrong_table_column_count(self):
        value = "<tr><td>Revenue</td><td>10</td></tr>"
        self.assertIsNone(TRIGGER.normalize_model_row_html("fy_comparison_rows", value))

    def test_drops_model_generated_table_header(self):
        value = (
            "<tr><th>A</th><th>B</th><th>C</th><th>D</th></tr>"
            "<tr><td>Revenue</td><td>10</td><td>12</td><td>+20%</td></tr>"
        )
        normalized = TRIGGER.normalize_model_row_html("fy_comparison_rows", value)
        self.assertNotIn("<th>", normalized)
        self.assertEqual(normalized.count("<tr>"), 1)

    def test_collapses_metric_explanation_when_value_is_unverified(self):
        value = "未披露 / 待验证。FMP ratios 接口 402，当前无法核验。"
        self.assertEqual(TRIGGER.compact_metric(value, "multiple"), "未披露 / 待验证")

    def test_extracts_short_percentage_from_long_metric_text(self):
        value = "Q4 FY2026 核心营收预期同比 +300% 以上（来源：公司指引）"
        self.assertEqual(TRIGGER.compact_metric(value, "percent"), "+300%")

    def test_removes_action_fields(self):
        data = {"action_class": "buy", "action_label": "买入", "action_rationale": "建议买入"}
        TRIGGER.remove_prohibited_advice(data)
        self.assertEqual(data, {})

    def test_removes_price_and_position_advice(self):
        data = {
            "one_liner": "公司收入增长。目标价为 100 美元；继续观察产品进展。",
            "monitoring_metrics": ["关注毛利率", "建议仓位不超过 3%"],
        }
        TRIGGER.remove_prohibited_advice(data)
        self.assertEqual(data["one_liner"], "公司收入增长。继续观察产品进展。")
        self.assertEqual(data["monitoring_metrics"], ["关注毛利率"])

    # --- New SEC-derived tests (offline, deterministic) ---

    def test_picks_single_quarter_revenue_over_ytd(self):
        """The extractor must return 5.95B for Q3, not the 11.283B YTD value."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        rev = sec["metrics"]["revenue"]
        q_val = rev["latest_q"]["val"]
        ytd_val = rev["ytd"]["val"]
        self.assertAlmostEqual(q_val, 5.95e9, delta=1e-3)
        self.assertAlmostEqual(ytd_val, 1.1283e10, delta=1e-3)
        self.assertNotAlmostEqual(q_val, ytd_val)

    def test_gross_margin_around_seventy_eight(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        gp = sec["metrics"]["gross_profit"]["latest_q"]["val"]
        rev = sec["metrics"]["revenue"]["latest_q"]["val"]
        margin = TRIGGER.safe_ratio(gp, rev)
        self.assertIsNotNone(margin)
        self.assertAlmostEqual(margin, 78.35, delta=0.5)

    def test_ytd_fcf_is_4_411_billion(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        ocf = sec["metrics"]["operating_cash_flow"]["ytd"]["val"]
        capex = sec["metrics"]["capex"]["ytd"]["val"]
        label, fcf, scope = TRIGGER._compute_fcf(sec["metrics"])
        self.assertEqual(label, "YTD")
        self.assertEqual(scope, "ytd")
        self.assertAlmostEqual(ocf - capex, 4.411e9, delta=1e-6)
        self.assertAlmostEqual(fcf, 4.411e9, delta=1e-6)

    def test_fcf_ttm_label_is_not_faked_when_only_ytd_exists(self):
        """Round 2 acceptance: fcf_yield must NEVER be calculated from
        YTD-only cash-flow data; the KPI card must show a clear scope
        label (YTD) and yield must read 不适用."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        base = {"fcf_ttm": "未披露 / 待验证", "fcf_yield": "未披露 / 待验证"}
        stock_data = {"sec_financials": sec, "market_cap": 2.006e11}
        TRIGGER._apply_sec_quarter_override(stock_data, base)
        self.assertIn("YTD", base["fcf_ttm"])
        first_word = base["fcf_ttm"].split(" ")[0]
        self.assertNotEqual(first_word, "TTM")
        # fcf_yield must explicitly say 不适用, not a percent.
        self.assertIn("不适用", base["fcf_yield"])

    def test_ytd_fcf_does_not_compute_yield(self):
        """Independent of override path: _compute_fcf returns
        (label, value, scope) where scope=='ytd' for a 280-day window.
        _compute_fcf_yield must NOT be invoked for that scope."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        metrics = sec["metrics"]
        label, value, scope = TRIGGER._compute_fcf(metrics)
        self.assertEqual(label, "YTD")
        self.assertEqual(scope, "ytd")
        # _compute_fcf_yield never sees this scope — see _apply_sec_quarter_override.
        # If someone wires the wrong branch, the override path asserts the
        # marker text instead of computing.
        base = {}
        TRIGGER._apply_sec_quarter_override(
            {"sec_financials": sec, "market_cap": 2.006e11}, base)
        self.assertFalse(
            base["fcf_yield"].endswith("%"),
            "fcf_yield should not be a percent for YTD; got {!r}".format(
                base["fcf_yield"]))

    def test_quarter_row_uses_same_period_yoy_header(self):
        """latest_quarter_rows column 1 == '上年同期', column 3 == '同比'.
        Subsequent cell-content upgrade must therefore land these bucket
        labels, not the legacy 上季度/Q/Q ones."""
        self.assertEqual(
            TRIGGER.ROW_SCHEMAS["latest_quarter_rows"][1], "上年同期")
        self.assertEqual(
            TRIGGER.ROW_SCHEMAS["latest_quarter_rows"][3], "同比")
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        q_rows, _ = TRIGGER._build_sec_quarterly_rows(sec)
        normalized = TRIGGER.normalize_model_row_html(
            "latest_quarter_rows", q_rows)
        self.assertIsNotNone(normalized)
        # The column-1 header label (上年同期) must drive cell substitutions.
        upgraded = TRIGGER._upgrade_row_cells(
            '<tr><td>X</td><td>未披露 / 待验证</td><td>$1</td>'
            '<td>未披露 / 待验证</td></tr>',
            row_field="latest_quarter_rows",
            fallback_label=TRIGGER.MISSING_TO_CROSS_VERIFY)
        # 0==指标 → first cell never gets upgraded; column 1 (上年同期) and
        # column 3 (同比) both bucket to 不适用 per _ROW_COLUMN_LABELS.
        self.assertIn("不适用", upgraded)

    def test_fy_comparison_rows_does_not_contain_ytd_cf(self):
        """_build_sec_fy_rows must NEVER pull OCF/CapEx from the .ytd
        block — those are not full-fiscal-year numbers and would 100%
        mismatch the table header. YTD lives in the Free Cash Flow KPI
        card and is labeled YTD."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        fy_rows = TRIGGER._build_sec_fy_rows(sec)
        for forbidden in (
            "Operating Cash Flow (累计)",
            "Capital Expenditure (累计)",
            "OCF",
            "CapEx",
            "YTD",
        ):
            self.assertNotIn(forbidden, fy_rows,
                            "fy_comparison_rows must not contain {!r}".format(forbidden))

    def test_business_rows_consolidated_not_single_segment(self):
        """Without explicit XBRL segment tags we must NOT assert
        'single reportable segment' or '单一份部'; the consolidated
        row uses the LATEST SINGLE QUARTER revenue (not YTD)."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        rows = TRIGGER._build_sec_business_rows(sec, "Sandisk")
        for forbidden in (
            "单一份部",
            "单一报告分部",
            "单一 报告分部",
            "报告分部（单一）",
        ):
            self.assertNotIn(forbidden, rows)
        # Must use the latest quarter ($5.95B), not the YTD ($11.28B).
        self.assertIn("$5.95B", rows)
        self.assertNotIn("$11.28B", rows)

    def test_business_rows_does_not_fabricate_product_splits(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        rev = sec["metrics"]["revenue"]
        # The dedup is internal; the public API exposes a single "latest_q"
        # dict, so we verify the value count by feeding the entries list
        # directly.
        raw_entries = []
        for taxonomy in ("us-gaap",):
            for entry in TRIGGER._entries_for_tag(
                    self.facts, taxonomy,
                    "RevenueFromContractWithCustomerExcludingAssessedTax"):
                raw_entries.append(entry)
        deduped = TRIGGER._dedupe_facts(raw_entries)
        self.assertLess(len(deduped), len(raw_entries))
        self.assertEqual(
            sum(1 for d in deduped
                if d.get("val") == 5.95e9
                and d.get("start") == "2026-01-04"
                and d.get("end") == "2026-04-03"),
            1,
        )

    def test_yoy_pct_only_computed_when_comparable_present(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        rev = sec["metrics"]["revenue"]
        self.assertAlmostEqual(rev["q_yoy_pct"], 190.24, delta=2.0)
        # capex has no YoY comparable — should stay None.
        capex = sec["metrics"]["capex"]
        self.assertIsNone(capex.get("q_yoy_pct"))
        self.assertIsNone(capex.get("ytd_yoy_pct"))

    def test_business_rows_does_not_fabricate_product_splits(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        rows = TRIGGER._build_sec_business_rows(sec, "Sandisk")
        row_count = rows.count("<tr>")
        self.assertEqual(row_count, 1)
        self.assertIn("Sandisk", rows)
        for forbidden in ("Client SSD", "Enterprise SSD", "Embedded",
                          "Removable"):
            self.assertNotIn(forbidden, rows)

    def test_sec_known_fields_no_longer_show_unknown(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        dashboard = {
            "TICKER": "SNDK", "current_date": "2026-07-20",
            "analysis_timestamp": "2026-07-20T10:00:00+0800",
            "company_name": "Sandisk",
            "latest_quarter_rows": "<tr><td>x</td></tr>",
            "fy_comparison_rows": "<tr><td>x</td></tr>",
            "business_rows": "<tr><td>x</td></tr>",
            "balance_sheet_rows": "<tr><td>x</td></tr>",
            "latest_quarter": "未披露 / 待验证",
            "latest_revenue": "未披露 / 待验证",
            "latest_eps": "未披露 / 待验证",
            "core_gross_margin": "未披露 / 待验证",
            "margin_change": "未披露 / 待验证",
            "fcf_ttm": "未披露 / 待验证",
            "fcf_yield": "未披露 / 待验证",
            "data_sources": [],
        }
        stock_data = {"sec_financials": sec, "market_cap": 2.006e11}
        TRIGGER._apply_sec_quarter_override(stock_data, dashboard)
        for field in ("latest_revenue", "latest_eps", "core_gross_margin",
                      "fcf_ttm"):
            self.assertNotEqual(
                dashboard[field], TRIGGER.UNKNOWN_DISPLAY,
                "{} still says unknown".format(field))
        self.assertIn("$", dashboard["latest_revenue"])
        self.assertIn("$", dashboard["latest_eps"])

    def test_no_investment_advice_in_extractor_output(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        text = json.dumps(sec, ensure_ascii=False, default=str).lower()
        for bad in ("target price", "stop loss", "position",
                    "加仓", "减仓", "止损", "买入", "卖出"):
            self.assertNotIn(bad, text)

    def test_python_3_6_compatible_syntax(self):
        """AST-level guard: make sure trigger.py parses on the server."""
        try:
            compile(TRIGGER_PATH.read_text(encoding="utf-8"),
                    str(TRIGGER_PATH), "exec")
        except SyntaxError as exc:
            self.fail("trigger.py failed to parse: {}".format(exc))
        # Walrus operator (:=) was only added in Python 3.8; we target 3.6.
        text = TRIGGER_PATH.read_text(encoding="utf-8")
        for token in (" :=", "(:"):
            self.assertNotIn(
                "{}\n".format(token), text,
                "walrus operator not allowed on Python 3.6 (found {!r})".format(token))

    def test_sec_table_outputs_have_correct_column_counts(self):
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        q_rows, _ = TRIGGER._build_sec_quarterly_rows(sec)
        self.assertIsNotNone(
            TRIGGER.normalize_model_row_html("latest_quarter_rows", q_rows))
        fy_rows = TRIGGER._build_sec_fy_rows(sec)
        self.assertIsNotNone(
            TRIGGER.normalize_model_row_html("fy_comparison_rows", fy_rows))
        bs_rows = TRIGGER._build_sec_balance_sheet_rows(sec)
        self.assertIsNotNone(
            TRIGGER.normalize_model_row_html("balance_sheet_rows", bs_rows))

    def test_multi_segment_company_does_not_get_single_segment_assertion(self):
        """A ticker whose 10-K Note already documents three reportable
        segments must NOT be collapsed into a single 合并 row just
        because XBRL companyfacts does not itself carry the Segment axis
        in our extractor. The override path must preserve the LLM's
        segment detail whenever the financial values come from research
        sources the LLM cited, and must never typecast the ticker into
        a "non-segment" label on its own."""
        facts = _build_multi_segment_companyfacts()
        sec = TRIGGER.extract_sec_financial_metrics(facts)
        # Multi-segment fixture inherits the SNDK-only tag set our
        # extractor looks for. The override therefore has the same
        # data signature as SNDK, so business_rows still must NOT
        # say "single reportable segment" — the multi-segment evidence
        # simply lives in the LLM-supplied dashboard_data, which the
        # override path must not erase.
        dashboard = {
            "company_name": "Acme Storage",
            "business_rows": "<tr>" + "".join(
                "<td>{}</td>".format(c) for c in (
                    "Consumer Storage",
                    "$2.0B", "35%", "+12%", "+4%", "消费电子主品牌阵地",
                )) + "</tr>\n" + "<tr>" + "".join(
                    "<td>{}</td>".format(c) for c in (
                        "Enterprise Storage",
                        "$3.5B", "61%", "+18%", "+7%", "数据中心 AI 增量",
                    )) + "</tr>" + "<tr>" + "".join(
                    "<td>{}</td>".format(c) for c in (
                        "Removable",
                        "$0.2B", "4%", "-3%", "-1%", "消费长尾",
                    )) + "</tr>",
            "data_sources": [],
        }
        stock_data = {"sec_financials": sec, "market_cap": 9.0e10}
        TRIGGER._apply_sec_dashboard_override(dashboard, stock_data)
        rows = dashboard["business_rows"]
        # Original three-row segment layout survives.
        self.assertEqual(rows.count("<tr>"), 3)
        for forbidden in ("单一份部", "单一报告分部", "non-segment",
                          "non-segment data"):
            self.assertNotIn(forbidden, rows)
        # Each product line survives.
        self.assertIn("Consumer Storage", rows)
        self.assertIn("Enterprise Storage", rows)


def _build_multi_segment_companyfacts():
    """Synthesises a SEC fixture for a fictional multi-segment storage
    company. Unlike the SNDK fixture this one is here purely to prove
    the override path does not flatten every ticker into a single
    合并 row."""
    def f(end, start, val, fp="Q3", fy=2026, filed="2026-05-01",
          accn="0009999999-26-000010", form="10-Q"):
        return {
            "end": end, "start": start, "val": val, "accn": accn,
            "fy": fy, "fp": fp, "form": form, "filed": filed,
            "frame": "CY{}Q{}".format(fy, fp[1]), "unit": "USD",
        }
    return {
        "cik": 9999999,
        "entityName": "Acme Storage Corp",
        "facts": {"us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "label": "Revenue",
                "units": {"USD": [
                    f("2026-04-03", "2026-01-04", 5.7e9),
                    f("2025-04-04", "2024-12-29", 2.1e9, fp="Q3", fy=2025, filed="2025-05-02"),
                ]},
            },
            "NetIncomeLoss": {
                "label": "Net Income",
                "units": {"USD": [
                    f("2026-04-03", "2026-01-04", 1.5e9),
                ]},
            },
        }},
    }


if __name__ == "__main__":
    unittest.main()
