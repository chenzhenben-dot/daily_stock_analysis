# -*- coding: utf-8 -*-
"""
data_provider/yfinance_fetcher 中美股指数获取逻辑的单元测试

使用 unittest.mock 模拟 yfinance API 响应，覆盖：
- _fetch_yf_ticker_data 单指数数据解析
- _get_us_main_indices 美股指数批量获取及异常场景
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd

# 在导入 data_provider 前 mock 可能缺失的依赖，避免环境差异导致测试无法运行
if 'fake_useragent' not in sys.modules:
    sys.modules['fake_useragent'] = MagicMock()

# 确保能导入项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _make_mock_hist(close: float, prev_close: float, high: float = None, low: float = None) -> pd.DataFrame:
    """构造模拟的 history DataFrame，包含计算涨跌幅所需字段"""
    high = high if high is not None else close + 1
    low = low if low is not None else close - 1
    return pd.DataFrame({
        'Close': [prev_close, close],
        'Open': [prev_close - 0.5, close - 0.3],
        'High': [prev_close + 1, high],
        'Low': [prev_close - 1, low],
        'Volume': [1000000.0, 1200000.0],
    }, index=pd.DatetimeIndex(['2025-02-16', '2025-02-17']))


def _make_mock_yf_with_per_symbol_history(history_map):
    """构造 mock yf，按 symbol 路由 history 返回值。

    ``history_map`` 是 ``{ yf_symbol: history_dataframe_or_exception_or_callable }``。
    如果值是 ``pd.DataFrame``（含空 DataFrame）则直接返回；如果是 ``Exception`` 则抛；
    如果是 ``callable``，按 ``history(period='2d')`` 调它。
    """
    def make_ticker(symbol):
        ticker = MagicMock()
        ticker._ticker_symbol = symbol
        value = history_map.get(symbol)

        def history_side_effect(*args, **kwargs):
            if isinstance(value, Exception):
                raise value
            if callable(value):
                return value(*args, **kwargs)
            return value

        ticker.history.side_effect = history_side_effect
        return ticker

    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = make_ticker
    return mock_yf


def _make_mock_yf(hist_df: pd.DataFrame):
    """构造模拟的 yf 模块，Ticker().history() 返回给定 DataFrame"""
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist_df
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker
    return mock_yf


class TestFetchYfTickerData(unittest.TestCase):
    """_fetch_yf_ticker_data 单指数取数逻辑测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_returns_dict_with_correct_fields(self):
        """正常数据应返回包含 code/name/current/change_pct 等字段的字典"""
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNotNone(result)
        self.assertEqual(result['code'], 'SPX')
        self.assertEqual(result['name'], '标普500指数')
        self.assertEqual(result['current'], 5100.0)
        self.assertEqual(result['prev_close'], 5000.0)
        self.assertEqual(result['change'], 100.0)
        self.assertAlmostEqual(result['change_pct'], 2.0)
        self.assertIn('open', result)
        self.assertIn('high', result)
        self.assertIn('low', result)
        self.assertIn('volume', result)
        self.assertIn('amount', result)
        self.assertIn('amplitude', result)

    def test_returns_none_when_history_empty(self):
        """history 为空时应返回 None"""
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNone(result)

    def test_single_row_history_uses_same_as_prev(self):
        """仅一行数据时 prev_close 等于 current，change_pct 为 0"""
        mock_hist = _make_mock_hist(close=5000.0, prev_close=5000.0)
        mock_hist = mock_hist.iloc[[-1]]
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._fetch_yf_ticker_data(mock_yf, '^GSPC', '标普500指数', 'SPX')

        self.assertIsNotNone(result)
        self.assertEqual(result['change_pct'], 0.0)


class TestGetUsMainIndices(unittest.TestCase):
    """_get_us_main_indices 美股指数批量获取测试"""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_returns_list_when_mock_succeeds(self, mock_get_symbol):
        """当映射与取数均成功时返回指数列表"""
        def get_symbol(code):
            mapping = {
                'SPX': ('^GSPC', '标普500指数'),
                'IXIC': ('^IXIC', '纳斯达克综合指数'),
                'NDX100': ('^NDX', '纳斯达克100指数'),
                'DJI': ('^DJI', '道琼斯工业指数'),
                'VIX': ('^VIX', 'VIX恐慌指数'),
            }
            return mapping.get(code, (None, None))

        mock_get_symbol.side_effect = get_symbol
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(
            [item['code'] for item in result],
            ['SPX', 'IXIC', 'NDX100', 'DJI', 'VIX'],
        )
        for item in result:
            self.assertIn('code', item)
            self.assertIn('name', item)
            self.assertIn('current', item)
            self.assertIn('change_pct', item)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_handles_empty_history_gracefully(self, mock_get_symbol):
        """部分指数 history 为空时仍返回能取到数据的指数"""
        call_count = [0]

        def get_symbol(code):
            return ('^GSPC', '标普500指数') if code == 'SPX' else (
                ('^IXIC', '纳斯达克综合指数') if code == 'IXIC' else (None, None)
            )

        def history_side_effect(period):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_mock_hist(close=5100.0, prev_close=5000.0)
            return pd.DataFrame()

        mock_get_symbol.side_effect = get_symbol
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = history_side_effect
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_returns_none_when_all_fail(self, mock_get_symbol):
        """全部取数失败时返回 None"""
        mock_get_symbol.return_value = (None, None)
        mock_yf = _make_mock_yf(pd.DataFrame())

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNone(result)

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_handles_ticker_exception(self, mock_get_symbol):
        """所有 ticker 抛异常时，NDX100 仍写入占位行（其它主指数失败时整批丢弃）。"""
        mock_get_symbol.return_value = ('^GSPC', '标普500指数')
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = Exception("Network error")
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        # NDX100 通过双重失败占位保留；其它指数（SPX/IXIC/DJI/VIX）数据全部失败时不写入。
        codes = [item['code'] for item in result]
        self.assertIn('NDX100', codes)
        ndx_row = next(item for item in result if item['code'] == 'NDX100')
        self.assertTrue(ndx_row.get('data_unavailable'))

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_skips_unknown_index_code(self, mock_get_symbol):
        """get_us_index_yf_symbol 返回 (None, None) 的代码应被跳过"""
        def get_symbol(code):
            if code == 'SPX':
                return ('^GSPC', '标普500指数')
            return (None, None)

        mock_get_symbol.side_effect = get_symbol
        mock_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf(mock_hist)

        result = self.fetcher._get_us_main_indices(mock_yf)

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['code'], 'SPX')

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_ndx100_falls_back_to_qqq_when_ndx_history_empty(self, mock_get_symbol):
        """^NDX 空 history → 回落到 QQQ；QQQ 行带 proxy/source 标记。"""
        def get_symbol(code):
            mapping = {
                'SPX': ('^GSPC', '标普500指数'),
                'IXIC': ('^IXIC', '纳斯达克综合指数'),
                'NDX100': ('^NDX', '纳斯达克100指数'),
                'DJI': ('^DJI', '道琼斯工业指数'),
                'VIX': ('^VIX', 'VIX恐慌指数'),
            }
            return mapping.get(code, (None, None))

        mock_get_symbol.side_effect = get_symbol

        primary_hist = _make_mock_hist(close=21000.0, prev_close=20500.0)
        proxy_hist = _make_mock_hist(close=500.0, prev_close=495.0)
        mock_yf = _make_mock_yf_with_per_symbol_history({
            '^GSPC': primary_hist,
            '^IXIC': primary_hist,
            '^NDX': pd.DataFrame(),
            'QQQ': proxy_hist,
            '^DJI': primary_hist,
            '^VIX': primary_hist,
        })

        result = self.fetcher._get_us_main_indices(mock_yf)

        codes = [item['code'] for item in result]
        self.assertIn('NDX100', codes)
        ndx_row = next(item for item in result if item['code'] == 'NDX100')
        self.assertTrue(ndx_row.get('proxy'))
        self.assertEqual(ndx_row.get('source'), 'nasdaq100_qqq_etf_proxy')
        self.assertIn('QQQ ETF', ndx_row['name'])

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_ndx100_falls_back_to_qqq_when_ndx_ticker_throws(self, mock_get_symbol):
        """^NDX 抛异常 → 回落到 QQQ。"""
        def get_symbol(code):
            mapping = {
                'SPX': ('^GSPC', '标普500指数'),
                'IXIC': ('^IXIC', '纳斯达克综合指数'),
                'NDX100': ('^NDX', '纳斯达克100指数'),
                'DJI': ('^DJI', '道琼斯工业指数'),
                'VIX': ('^VIX', 'VIX恐慌指数'),
            }
            return mapping.get(code, (None, None))

        mock_get_symbol.side_effect = get_symbol

        primary_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        proxy_hist = _make_mock_hist(close=500.0, prev_close=495.0)
        mock_yf = _make_mock_yf_with_per_symbol_history({
            '^GSPC': primary_hist,
            '^IXIC': primary_hist,
            '^NDX': RuntimeError("yfinance network error"),
            'QQQ': proxy_hist,
            '^DJI': primary_hist,
            '^VIX': primary_hist,
        })

        result = self.fetcher._get_us_main_indices(mock_yf)

        codes = [item['code'] for item in result]
        self.assertIn('NDX100', codes)
        ndx_row = next(item for item in result if item['code'] == 'NDX100')
        self.assertTrue(ndx_row.get('proxy'))
        self.assertEqual(ndx_row.get('source'), 'nasdaq100_qqq_etf_proxy')

    @patch('data_provider.yfinance_fetcher.get_us_index_yf_symbol')
    def test_ndx100_keeps_unavailable_placeholder_when_both_fail(self, mock_get_symbol):
        """^NDX 与 QQQ 都失败 → NDX100 行保留，data_unavailable=True。"""
        def get_symbol(code):
            mapping = {
                'SPX': ('^GSPC', '标普500指数'),
                'IXIC': ('^IXIC', '纳斯达克综合指数'),
                'NDX100': ('^NDX', '纳斯达克100指数'),
                'DJI': ('^DJI', '道琼斯工业指数'),
                'VIX': ('^VIX', 'VIX恐慌指数'),
            }
            return mapping.get(code, (None, None))

        mock_get_symbol.side_effect = get_symbol

        primary_hist = _make_mock_hist(close=5100.0, prev_close=5000.0)
        mock_yf = _make_mock_yf_with_per_symbol_history({
            '^GSPC': primary_hist,
            '^IXIC': primary_hist,
            '^NDX': pd.DataFrame(),
            'QQQ': pd.DataFrame(),
            '^DJI': primary_hist,
            '^VIX': primary_hist,
        })

        result = self.fetcher._get_us_main_indices(mock_yf)

        codes = [item['code'] for item in result]
        self.assertIn('NDX100', codes)
        ndx_row = next(item for item in result if item['code'] == 'NDX100')
        self.assertTrue(ndx_row.get('data_unavailable'))
        self.assertEqual(ndx_row.get('source'), 'unavailable')
        self.assertEqual(ndx_row['current'], 0.0)


if __name__ == '__main__':
    unittest.main()
