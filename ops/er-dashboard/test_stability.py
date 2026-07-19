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


if __name__ == "__main__":
    unittest.main()
