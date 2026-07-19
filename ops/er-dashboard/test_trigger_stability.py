import importlib.util
import unittest
from pathlib import Path


TRIGGER_PATH = Path(__file__).resolve().with_name("trigger.py")
if not TRIGGER_PATH.exists():
    TRIGGER_PATH = Path("work/trigger.py")
SPEC = importlib.util.spec_from_file_location("er_trigger", str(TRIGGER_PATH))
TRIGGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIGGER)


class TriggerStabilityTests(unittest.TestCase):
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

    def test_truncates_header_rationale(self):
        data = {field: "未披露 / 待验证" for field in TRIGGER.SHORT_DISPLAY_FIELDS}
        data["action_rationale"] = "结论" * 100
        TRIGGER.compact_dashboard_display(data)
        self.assertLessEqual(len(data["action_rationale"]), 160)
        self.assertTrue(data["action_rationale"].endswith("…"))


if __name__ == "__main__":
    unittest.main()
