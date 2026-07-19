#!/usr/bin/env python3
"""
Equity Research Dashboard Generator
从 JSON 数据 + HTML 模板生成最终看板

Usage:
    python3 dashboard-generator.py <TICKER> <YYYY-MM-DD> <data-json-file>

Or programmatically:
    from dashboard_generator import build_dashboard
    html = build_dashboard(data_dict, template_path, output_path)
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime


def find_all_placeholders(template: str) -> list:
    """提取模板里所有 {{placeholder}} 占位符"""
    return list(set(re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", template)))


def render_template(template: str, data: dict) -> str:
    """
    把 {{key}} 替换成 data[key]（支持缺失值显示空字符串）。
    也支持 {{key_class}} 这类条件 class 名（agent 在数据里给完整 class 名）。
    """
    def replacer(match):
        key = match.group(1)
        val = data.get(key, "")
        if val is None:
            return ""
        return str(val)
    return re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", replacer, template)


def list_to_rows_html(items, row_template: str = "<li>{item}</li>") -> str:
    """把 list 拼成 <li> 列表 HTML"""
    if not items:
        return ""
    if isinstance(items, list) and items and isinstance(items[0], str):
        return "\n".join(row_template.format(item=item) for item in items)
    return "\n".join(items)


def build_dashboard(
    data: dict,
    template_path: str = None,
    output_path: str = None,
    auto_open: bool = False,
) -> str:
    """
    拿数据 + 模板，生成 HTML 看板并写入文件。

    data: dict,所有 {{placeholder}} 的值
    template_path: 模板路径,默认在 skill references 里
    output_path: 输出路径,默认 ~/Desktop/equity-dashboards/<TICKER>-<DATE>.html
    """
    if template_path is None:
        skill_dir = Path.home() / ".claude/skills/equity-research/references"
        template_path = skill_dir / "dashboard-template.html"

    template = Path(template_path).read_text(encoding="utf-8")

    # 自动处理 list-of-str 字段 → HTML 行
    list_fields = [
        "monitoring_metrics", "product_milestones", "valuation_assumptions",
        "invalidation_conditions", "sell_conditions", "data_conflicts", "data_sources",
    ]
    for field in list_fields:
        if field in data and isinstance(data[field], list):
            data[field] = list_to_rows_html(
                [f"<li>{x}</li>" for x in data[field]]
            )

    # 处理 table rows 字段（agent 给 list of HTML 字符串）
    row_fields = [
        "latest_quarter_rows", "fy_comparison_rows", "segment_rows", "guidance_rows",
        "valuation_rows", "balance_sheet_rows", "comp_financial_rows",
        "customer_rows", "catalyst_rows",
        "business_rows", "product_rows", "chain_rows",
    ]
    for field in row_fields:
        if field in data and isinstance(data[field], list):
            data[field] = "\n".join(data[field])

    # 时间戳默认
    data.setdefault("analysis_timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    html = render_template(template, data)

    if output_path is None:
        ticker = data.get("TICKER", "UNKNOWN")
        date = data.get("current_date", datetime.now().strftime("%Y-%m-%d"))
        out_dir = Path.home() / "Desktop/equity-dashboards"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{ticker}-{date}.html"

    Path(output_path).write_text(html, encoding="utf-8")

    if auto_open:
        import subprocess
        subprocess.Popen(["open", str(output_path)])

    return str(output_path)


def main():
    """CLI 入口:python3 dashboard-generator.py <data.json>"""
    if len(sys.argv) < 2:
        print("Usage: dashboard-generator.py <data.json>")
        sys.exit(1)

    data_file = Path(sys.argv[1])
    data = json.loads(data_file.read_text(encoding="utf-8"))
    output = build_dashboard(data)
    print(f"OK: {output}")


if __name__ == "__main__":
    main()
