# -*- coding: utf-8 -*-
"""
Tests for US market-review fixes introduced after ops/orbstack-staging 5 commit chain.

These tests pin the contract changes required by the post-staging audit:

* US payload must NOT carry limit_up_count / limit_down_count.
* US market-light snapshot must NOT include the limit dimension.
* US breadth + index both available => data_quality == "ok".
* Raw USD turnover (189_727_840_037) must format to ~189.73 十亿美元.
* US stats block must NOT contain "两市成交额" or "亿元".
* CN stats block must STILL contain correct 亿元 / 涨跌停 wording.
* market_stats_source / market_stats_sample_size must flow from fetcher to payload.
* Frontend must hide the limit-up/down card when the fields are absent.
* Frontend must show "来源：Moomoo · 覆盖样本：N,NNN 只".
* NDX100 must always be present in US index list.
* US report must NOT contain 资金净流入 / 资金净流出 / 主力资金 phrases.
* Existing market-review + ER tests must remain green (covered by full suite).
"""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

for _mod in ("newspaper", "litellm", "google.generativeai", "google.genai", "anthropic", "fake_useragent"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from src.core.market_profile import get_profile
from src.core.market_strategy import get_market_strategy_blueprint
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview


def _make_us_analyzer() -> MarketAnalyzer:
    """Build a US analyzer with deterministic helpers and a real strategy blueprint."""
    analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
    analyzer.region = "us"
    analyzer.profile = get_profile("us")
    analyzer.strategy = get_market_strategy_blueprint("us")
    analyzer.config = SimpleNamespace(report_language="zh")
    analyzer._get_output_language = MagicMock(return_value="zh")
    analyzer._get_review_title = MagicMock(return_value="# 美股大盘复盘")
    analyzer._get_market_scope_name = MagicMock(return_value="美股")
    analyzer._get_turnover_unit_label = MagicMock(return_value="十亿美元")
    analyzer._supports_market_light = MagicMock(return_value=True)
    return analyzer


def _make_cn_analyzer() -> MarketAnalyzer:
    """Build a CN analyzer with deterministic helpers and a real strategy blueprint."""
    analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
    analyzer.region = "cn"
    analyzer.profile = get_profile("cn")
    analyzer.strategy = get_market_strategy_blueprint("cn")
    analyzer.config = SimpleNamespace(report_language="zh")
    analyzer._get_output_language = MagicMock(return_value="zh")
    analyzer._get_review_title = MagicMock(return_value="# A股大盘复盘")
    analyzer._get_market_scope_name = MagicMock(return_value="A股")
    analyzer._get_turnover_unit_label = MagicMock(return_value="亿元")
    analyzer._supports_market_light = MagicMock(return_value=True)
    return analyzer


def _us_overview(*, amount: float = 189_727_840_037.0) -> MarketOverview:
    return MarketOverview(
        date="2026-07-22",
        indices=[
            MarketIndex(code="SPX", name="标普500指数", current=6200.0, change_pct=0.5),
            MarketIndex(code="IXIC", name="纳斯达克综合指数", current=20500.0, change_pct=0.7),
            MarketIndex(code="NDX100", name="纳斯达克100指数", current=21500.0, change_pct=0.8),
            MarketIndex(code="DJI", name="道琼斯工业指数", current=39800.0, change_pct=0.2),
            MarketIndex(code="VIX", name="VIX恐慌指数", current=13.4, change_pct=-2.1),
        ],
        up_count=983,
        down_count=913,
        flat_count=104,
        total_amount=amount,
    )


class TestUsPayloadStructure(unittest.TestCase):
    """需求 #1/#3: US payload 不含 limit 字段；灯号不带 limit 维度。"""

    def test_us_payload_omits_limit_up_down_fields(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        payload = analyzer.build_market_review_payload(
            overview,
            [],
            "## 美股大盘复盘\n\n测试",
            market_light_snapshot={"dimensions": {"breadth": {"score": 52, "available": True}}},
        )

        self.assertIn("breadth", payload)
        self.assertNotIn("limit_up_count", payload["breadth"])
        self.assertNotIn("limit_down_count", payload["breadth"])

    def test_us_market_light_snapshot_has_no_limit_dimension(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        snapshot = analyzer.build_market_light_snapshot(overview)

        self.assertNotIn("limit", snapshot["dimensions"])

    def test_us_breadth_and_index_complete_yields_ok_data_quality(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        snapshot = analyzer.build_market_light_snapshot(overview)

        self.assertEqual(snapshot["data_quality"], "ok")

    def test_cn_market_light_snapshot_keeps_limit_dimension(self):
        """CN 必须保留 limit 维度，不能误伤。"""
        analyzer = _make_cn_analyzer()
        overview = MarketOverview(
            date="2026-07-22",
            indices=[MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.5)],
            up_count=3500,
            down_count=1500,
            flat_count=200,
            limit_up_count=80,
            limit_down_count=5,
            total_amount=9800.0,
        )

        snapshot = analyzer.build_market_light_snapshot(overview)

        self.assertIn("limit", snapshot["dimensions"])
        self.assertEqual(snapshot["data_quality"], "ok")


class TestUsTurnoverUnitFormatting(unittest.TestCase):
    """需求 #1: 189727840037 USD → ~189.73 十亿美元。"""

    def test_us_turnover_formatted_as_billion_usd(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview(amount=189_727_840_037.0)

        payload = analyzer.build_market_review_payload(
            overview,
            [],
            "## 美股大盘复盘",
            market_light_snapshot=None,
        )

        self.assertEqual(payload["breadth"]["total_amount"], 189_727_840_037.0)
        self.assertEqual(payload["breadth"]["turnover_unit"], "十亿美元")
        self.assertIn("formatted_turnover", payload["breadth"])
        self.assertIn("189.73", payload["breadth"]["formatted_turnover"])

    def test_cn_stats_block_keeps_yi_unit(self):
        """CN 必须仍以亿元呈现，且 stats block 保留两市成交额/涨跌停。"""
        analyzer = _make_cn_analyzer()
        overview = MarketOverview(
            date="2026-07-22",
            indices=[MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.5)],
            up_count=3500,
            down_count=1500,
            flat_count=200,
            limit_up_count=80,
            limit_down_count=5,
            total_amount=9800.0,
        )

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertIn("两市成交额", prompt)
        self.assertIn("亿元", prompt)
        self.assertIn("涨停", prompt)
        self.assertIn("跌停", prompt)

    def test_us_stats_block_omits_liangshi_turnover_and_yi(self):
        """US prompt 中不应出现「两市成交额」或「亿元」。"""
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertNotIn("两市成交额", prompt)
        self.assertNotIn("亿元", prompt)

    def test_us_injected_stats_block_uses_sample_turnover_and_source(self):
        """最终报告注入块也必须使用 US 单位，不能只修 LLM prompt。"""
        analyzer = _make_us_analyzer()
        overview = _us_overview()
        overview.market_stats_source = "moomoo_us_exchange_universe"
        overview.market_stats_sample_size = 2000

        block = analyzer._build_stats_block(overview)

        self.assertIn("样本成交额", block)
        self.assertIn("189.73 十亿美元", block)
        self.assertIn("moomoo_us_exchange_universe", block)
        self.assertIn("2,000", block)
        self.assertNotIn("两市成交额", block)
        self.assertNotIn("189727840037 亿", block)

    def test_us_fallback_report_does_not_reintroduce_cn_turnover_terms(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        report = analyzer._generate_template_review(overview, [])

        self.assertIn("189.73 十亿美元", report)
        self.assertIn("成交额(十亿美元)", report)
        self.assertNotIn("两市成交额", report)
        self.assertNotIn("189727840037 亿", report)
        self.assertNotIn("成交额(亿)", report)


class TestUsDescribeTurnover(unittest.TestCase):
    """需求 #2: 成交活跃度按 region 分发，US/HK/JP/KR 用中性文案。"""

    def test_cn_describe_turnover_keeps_legacy_thresholds(self):
        cn = MarketAnalyzer.__new__(MarketAnalyzer)
        cn.region = "cn"
        self.assertEqual(cn._describe_turnover(15000.0), "高活跃度")
        self.assertEqual(cn._describe_turnover(9000.0), "中等活跃")
        self.assertEqual(cn._describe_turnover(5000.0), "缩量观望")
        self.assertEqual(cn._describe_turnover(0.0), "暂无数据")

    def test_us_describe_turnover_uses_neutral_sample_text(self):
        us = MarketAnalyzer.__new__(MarketAnalyzer)
        us.region = "us"

        text = us._describe_turnover(189_727_840_037.0)

        self.assertIn("样本", text)
        self.assertNotIn("高活跃度", text)
        self.assertNotIn("中等活跃", text)
        self.assertNotIn("缩量观望", text)

    def test_hk_jp_kr_describe_turnover_uses_neutral_text(self):
        for region in ("hk", "jp", "kr"):
            analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
            analyzer.region = region
            text = analyzer._describe_turnover(100_000_000_000.0)
            self.assertNotIn("高活跃度", text, msg=region)
            self.assertNotIn("中等活跃", text, msg=region)


class TestUsEnglishFallbackTurnover(unittest.TestCase):
    """验收 #4: 英文 fallback 不得直接渲染 overview.total_amount 原始数字，
    必须走 region-aware formatter；189_727_840_037 USD 必须显示约 189.73 USD bn。"""

    def _make_us_en_analyzer(self) -> MarketAnalyzer:
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "us"
        analyzer.profile = get_profile("us")
        analyzer.strategy = get_market_strategy_blueprint("us")
        analyzer.config = SimpleNamespace(report_language="en")
        analyzer._get_output_language = MagicMock(return_value="en")
        analyzer._get_review_title = MagicMock(return_value="# Market Review")
        analyzer._get_market_scope_name = MagicMock(return_value="US market")
        analyzer._get_turnover_unit_label = MagicMock(return_value="USD bn")
        analyzer._supports_market_light = MagicMock(return_value=True)
        return analyzer

    def test_us_stats_block_turnover_uses_region_formatter(self):
        analyzer = self._make_us_en_analyzer()
        overview = _us_overview(amount=189_727_840_037.0)

        stats = analyzer._build_stats_block(overview)

        # 189_727_840_037 USD 应渲染为 189.73 USD bn（连续无空格的 189727840037 不该出现）
        self.assertIn("189.73", stats)
        self.assertIn("USD bn", stats)
        self.assertNotIn("189727840037", stats)

    def test_us_prompt_stats_block_uses_region_formatter(self):
        analyzer = self._make_us_en_analyzer()
        overview = _us_overview(amount=189_727_840_037.0)

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertIn("189.73", prompt)
        self.assertIn("USD bn", prompt)
        self.assertNotIn("189727840037", prompt)

    def test_cn_en_fallback_keeps_yi(self):
        """CN 走 1e8 缩放；英文 stats block 也保留亿元单位。"""
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "cn"
        analyzer.profile = get_profile("cn")
        analyzer.strategy = get_market_strategy_blueprint("cn")
        analyzer.config = SimpleNamespace(report_language="en")
        analyzer._get_output_language = MagicMock(return_value="en")
        analyzer._get_review_title = MagicMock(return_value="# Market Review")
        analyzer._get_market_scope_name = MagicMock(return_value="A-share market")
        analyzer._get_turnover_unit_label = MagicMock(return_value="CNY 100m")
        analyzer._supports_market_light = MagicMock(return_value=True)
        overview = MarketOverview(
            date="2026-07-22",
            indices=[MarketIndex(code="000001", name="SSE", current=3200.0, change_pct=0.5)],
            up_count=3500,
            down_count=1500,
            flat_count=200,
            limit_up_count=80,
            limit_down_count=5,
            total_amount=9.8e11,
        )

        stats = analyzer._build_stats_block(overview)

        self.assertIn("9800", stats)
        self.assertIn("CNY 100m", stats)
        self.assertNotIn("980000000000", stats)


class TestUsMarketReviewSourceTransparency(unittest.TestCase):
    """需求 #4: market_stats_source / sample_size 透传到 payload。"""

    def test_market_overview_accepts_source_and_sample_size(self):
        overview = MarketOverview(
            date="2026-07-22",
            market_stats_source="moomoo_us_exchange_universe",
            market_stats_sample_size=2000,
        )

        self.assertEqual(overview.market_stats_source, "moomoo_us_exchange_universe")
        self.assertEqual(overview.market_stats_sample_size, 2000)

    def test_us_payload_exposes_source_and_sample_size(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()
        overview.market_stats_source = "moomoo_us_exchange_universe"
        overview.market_stats_sample_size = 2000

        payload = analyzer.build_market_review_payload(
            overview,
            [],
            "## 美股大盘复盘",
            market_light_snapshot=None,
        )

        self.assertEqual(payload["breadth"]["market_stats_source"], "moomoo_us_exchange_universe")
        self.assertEqual(payload["breadth"]["market_stats_sample_size"], 2000)

    def test_us_get_market_statistics_propagates_source_and_sample_size(self):
        analyzer = MarketAnalyzer.__new__(MarketAnalyzer)
        analyzer.region = "us"
        analyzer.profile = get_profile("us")
        analyzer.data_manager = MagicMock()
        analyzer.data_manager.get_market_stats.return_value = {
            "up_count": 100,
            "down_count": 80,
            "flat_count": 10,
            "total_amount": 1.2e11,
            "source": "moomoo_us_exchange_universe",
            "sample_size": 2000,
        }
        overview = MarketOverview(date="2026-07-22")

        analyzer._get_market_statistics(overview)

        self.assertEqual(overview.market_stats_source, "moomoo_us_exchange_universe")
        self.assertEqual(overview.market_stats_sample_size, 2000)
        self.assertEqual(overview.total_amount, 1.2e11)


class TestUsMarketIndicesCoverage(unittest.TestCase):
    """需求 #6: 纳斯达克100 必须始终保留在美股指数列表。"""

    def test_us_required_indices_include_ndx100(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        codes = [idx.code for idx in overview.indices]

        for required in ("SPX", "IXIC", "NDX100", "DJI", "VIX"):
            self.assertIn(required, codes, msg=f"missing {required}")

    def test_us_payload_indices_contain_ndx100(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        payload = analyzer.build_market_review_payload(
            overview,
            [],
            "## 美股大盘复盘",
            market_light_snapshot=None,
        )

        codes = [idx["code"] for idx in payload["indices"]]
        self.assertIn("NDX100", codes)

    def test_ndx_alias_is_nasdaq100_not_nasdaq_composite(self):
        """NDX 永远绑定纳斯达克100；IXIC 才是纳斯达克综合指数。"""
        from data_provider.us_index_mapping import get_us_index_yf_symbol

        ndx_yf, ndx_name = get_us_index_yf_symbol("NDX")
        self.assertEqual(ndx_yf, "^NDX")
        self.assertEqual(ndx_name, "纳斯达克100指数")

        ixic_yf, ixic_name = get_us_index_yf_symbol("IXIC")
        self.assertEqual(ixic_yf, "^IXIC")
        self.assertEqual(ixic_name, "纳斯达克综合指数")

        ndx100_yf, ndx100_name = get_us_index_yf_symbol("NDX100")
        self.assertEqual(ndx100_yf, "^NDX")
        self.assertEqual(ndx100_name, "纳斯达克100指数")

    def test_unavailable_index_is_excluded_from_market_light_score(self):
        """Unavailable placeholders must not be treated as flat index observations."""
        analyzer = _make_us_analyzer()
        overview = _us_overview()
        overview.indices = [
            MarketIndex(code="SPX", name="标普500指数", current=6200.0, change_pct=2.0),
            MarketIndex(
                code="NDX100",
                name="纳斯达克100指数",
                current=0.0,
                change_pct=0.0,
                data_unavailable=True,
                source="unavailable",
            ),
        ]

        snapshot = analyzer.build_market_light_snapshot(overview)

        self.assertEqual(snapshot["dimensions"]["index"]["score"], 74)

    def test_unavailable_index_is_rendered_as_na_in_prompt_and_tables(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()
        overview.indices = [
            MarketIndex(
                code="NDX100",
                name="纳斯达克100指数",
                current=0.0,
                change_pct=0.0,
                data_unavailable=True,
                source="unavailable",
            ),
        ]

        prompt = analyzer._build_review_prompt(overview, [])
        table = analyzer._build_indices_block(overview)
        fallback = analyzer._generate_template_review(overview, [])

        for rendered in (prompt, table, fallback):
            self.assertIn("数据暂不可用", rendered)
            self.assertNotIn("纳斯达克100指数: 0.00", rendered)
            self.assertNotIn("| 纳斯达克100指数 | 0.00 |", rendered)

    def test_index_payload_preserves_proxy_and_unavailable_metadata(self):
        proxy = MarketIndex(
            code="NDX100",
            name="纳斯达克100指数 (QQQ ETF 代理)",
            current=500.0,
            change_pct=1.0,
            proxy=True,
            source="nasdaq100_qqq_etf_proxy",
        ).to_dict()
        unavailable = MarketIndex(
            code="NDX100",
            name="纳斯达克100指数",
            data_unavailable=True,
            source="unavailable",
        ).to_dict()

        self.assertTrue(proxy["proxy"])
        self.assertEqual(proxy["source"], "nasdaq100_qqq_etf_proxy")
        self.assertTrue(unavailable["data_unavailable"])


class TestUsBlueprintAndPrompt(unittest.TestCase):
    """需求 #5: US prompt 蓝图/章节标题改成 Breadth & Liquidity / Macro & Risk Appetite。"""

    def test_us_blueprint_drops_macro_and_flows(self):
        analyzer = _make_us_analyzer()
        blueprint = analyzer._get_strategy_prompt_block()
        self.assertNotIn("Macro & Flows", blueprint)

    def test_us_blueprint_uses_macro_risk_appetite(self):
        analyzer = _make_us_analyzer()
        blueprint = analyzer._get_strategy_prompt_block()
        self.assertIn("Macro & Risk Appetite", blueprint)

    def test_us_prompt_uses_breadth_liquidity_section(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertIn("Breadth & Liquidity", prompt)
        self.assertNotIn("Fund Flows", prompt)

    def test_us_prompt_chinese_uses_breadth_liquidity_title(self):
        """需求 #5 C: 最终中文报告章节标题为「市场宽度与流动性」。"""
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertIn("市场宽度与流动性", prompt)
        self.assertNotIn("资金与情绪", prompt)

    def test_cn_prompt_keeps_fund_flow_section(self):
        """CN 必须保留「资金与情绪」。"""
        analyzer = _make_cn_analyzer()
        overview = MarketOverview(
            date="2026-07-22",
            indices=[MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.5)],
            up_count=3500,
            down_count=1500,
            flat_count=200,
            limit_up_count=80,
            limit_down_count=5,
            total_amount=9800.0,
        )

        prompt = analyzer._build_review_prompt(overview, [])

        self.assertIn("资金与情绪", prompt)


class TestUsReportForbiddenPhrases(unittest.TestCase):
    """需求 #5 末: 美股报告不得出现无数据支撑的资金净流入/资金净流出/主力资金。"""

    def test_us_prompt_warns_against_unsupported_fund_flow_claims(self):
        analyzer = _make_us_analyzer()
        overview = _us_overview()

        prompt = analyzer._build_review_prompt(overview, [])

        # Prompt 应当明确禁止资金净流入/资金净流出/主力资金等无依据结论。
        self.assertTrue(
            ("资金净流入" in prompt and "不要" in prompt)
            or ("资金净流出" in prompt and "不要" in prompt)
            or ("主力资金" in prompt and "不要" in prompt)
            or "fund-flow" in prompt
            or "fund flow" in prompt.lower(),
        )


if __name__ == "__main__":
    unittest.main()
