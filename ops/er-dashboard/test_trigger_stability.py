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
        label, fcf = TRIGGER._compute_ytd_fcf(sec["metrics"])
        self.assertEqual(label, "YTD")
        self.assertAlmostEqual(ocf - capex, 4.411e9, delta=1e-6)
        self.assertAlmostEqual(fcf, 4.411e9, delta=1e-6)

    def test_fcf_ttm_label_is_not_faked_when_only_ytd_exists(self):
        """Without a full TTM window the dashboard must NOT call the value TTM."""
        sec = TRIGGER.extract_sec_financial_metrics(self.facts)
        base = {"fcf_ttm": "未披露 / 待验证", "fcf_yield": "未披露 / 待验证"}
        stock_data = {"sec_financials": sec, "market_cap": 2.006e11}
        TRIGGER._apply_sec_quarter_override(stock_data, base)
        self.assertIn("YTD", base["fcf_ttm"])
        # The first word of fcf_ttm is the scope label; must not be "TTM".
        first_word = base["fcf_ttm"].split(" ")[0]
        self.assertNotEqual(first_word, "TTM")
        self.assertTrue(base["fcf_yield"].endswith("%"))

    def test_duplicate_context_is_deduplicated(self):
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


if __name__ == "__main__":
    unittest.main()
