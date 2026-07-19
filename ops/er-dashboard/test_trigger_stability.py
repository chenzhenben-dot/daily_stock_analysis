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


if __name__ == "__main__":
    unittest.main()
