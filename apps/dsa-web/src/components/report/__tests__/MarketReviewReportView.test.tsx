import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AnalysisReport, MarketReviewPayload } from '../../../types/analysis';
import { MarketReviewReportView } from '../MarketReviewReportView';

vi.mock('../../../api/history', () => ({
  historyApi: {
    getMarkdown: vi.fn(),
  },
}));

const englishMarketReviewReport: AnalysisReport = {
  meta: {
    queryId: 'market-review-q-1',
    stockCode: 'MARKET',
    stockName: 'Market Review',
    reportType: 'market_review',
    reportLanguage: 'en',
    createdAt: '2026-03-18T08:00:00Z',
  },
  summary: {
    analysisSummary: '',
    operationAdvice: '',
    trendPrediction: '',
    sentimentScore: undefined as unknown as number,
  },
};

const combinedMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'cn,hk',
  language: 'zh',
  rootTitle: '大盘复盘',
  markets: {
    cn: {
      title: 'A股市场',
      breadth: {
        upCount: 3120,
        downCount: 1420,
        limitUpCount: 72,
        limitDownCount: 4,
        totalAmount: 9600,
        turnoverUnit: '亿元',
      },
      indices: [{
        code: '000300',
        name: '沪深300',
        current: 3920.2,
        changePct: 1.2,
        high: 3940.5,
        low: 3860.1,
      }],
      sectors: {
        top: [{ name: '半导体', changePct: 2.35 }],
        bottom: [{ name: '煤炭', changePct: -1.1 }],
      },
      concepts: {
        top: [{ name: '机器人概念', changePct: 4.2 }],
        bottom: [{ name: '转基因', changePct: -2.05 }],
      },
    },
    hk: {
      title: '港股市场',
      breadth: {
        upCount: 680,
        downCount: 410,
        limitUpCount: 0,
        limitDownCount: 0,
        totalAmount: 1180,
        turnoverUnit: '亿港元',
      },
      indices: [{
        code: 'HSI',
        name: '恒生指数',
        current: 18920.4,
        changePct: -0.5,
        high: 19050.2,
        low: 18780.3,
      }],
    },
  },
};

const noBreadthMarketReviewPayload: MarketReviewPayload = {
  version: 1,
  kind: 'market_review',
  region: 'us',
  language: 'en',
  title: 'Market Review',
  rootTitle: 'Market Review',
  indices: [{
    code: 'SPX',
    name: 'S&P 500',
    current: 5200,
    changePct: 0.68,
    high: 5235.2,
    low: 5170.4,
  }],
  sectors: {
    top: [{ name: 'Technology', changePct: 1.9 }],
    bottom: [{ name: 'Energy', changePct: -0.8 }],
  },
  macro: [{
    seriesId: 'DGS10',
    nameZh: '美国10年期国债收益率',
    nameEn: '10-Year Treasury Yield',
    value: 4.56,
    previousValue: 4.54,
    change: 0.02,
    unit: '%',
    observationDate: '2026-07-10',
    source: 'FRED',
  }],
  news: [],
  sections: [],
};

describe('MarketReviewReportView', () => {
  it('uses localized summary card labels and fallbacks for English reports', () => {
    render(
      <MarketReviewReportView
        report={englishMarketReviewReport}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Review Summary')).toBeInTheDocument();
    expect(screen.getByText('No review summary yet')).toBeInTheDocument();
    expect(screen.getByText('Market Sentiment')).toBeInTheDocument();
    expect(screen.getByText('No score yet')).toBeInTheDocument();
    expect(screen.getByText('Breadth & Liquidity')).toBeInTheDocument();
    expect(screen.getByText('No breadth/liquidity view yet')).toBeInTheDocument();
    expect(screen.getByText('Risks & Watchlist')).toBeInTheDocument();
    expect(screen.getByText('No key observations yet')).toBeInTheDocument();
    expect(screen.queryByText('复盘摘要')).not.toBeInTheDocument();
    expect(screen.queryByText('暂无摘要')).not.toBeInTheDocument();
  });

  it('renders structured data for every market in a combined market review payload', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    const cnTab = screen.getByRole("tab", { name: "A股市场" });
    const hkTab = screen.getByRole("tab", { name: "港股市场" });
    expect(cnTab).toHaveAttribute("aria-selected", "true");
    expect(hkTab).toHaveAttribute("aria-selected", "false");
    expect(screen.getByText("沪深300")).toBeInTheDocument();
    expect(screen.getByText("3120")).toBeInTheDocument();

    fireEvent.click(hkTab);

    expect(hkTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("恒生指数")).toBeInTheDocument();
    expect(screen.getByText("680")).toBeInTheDocument();
    expect(screen.queryByText("沪深300")).not.toBeInTheDocument();
  });

  it('renders industry and concept rankings from structured market review payloads', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getAllByText('行业板块')).toHaveLength(2);
    expect(screen.getAllByText('概念板块')).toHaveLength(2);
    expect(screen.getByText('半导体')).toBeInTheDocument();
    expect(screen.getByText('机器人概念')).toBeInTheDocument();
    expect(screen.getByText('+4.20%')).toBeInTheDocument();
    expect(screen.getByText('-2.05%')).toBeInTheDocument();
  });

  it('localizes structured market data labels for Chinese reports', () => {
    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('结构化大盘数据')).toBeInTheDocument();
    expect(screen.getAllByText('上涨家数')).toHaveLength(1);
    expect(screen.getAllByText('下跌家数')).toHaveLength(1);
    expect(screen.getAllByText('涨停/跌停')).toHaveLength(1);
    expect(screen.getAllByText('成交额')).toHaveLength(1);
    expect(screen.getAllByText('指数')).toHaveLength(1);
    expect(screen.getAllByText('最新')).toHaveLength(1);
    expect(screen.getAllByText('涨跌幅')).toHaveLength(1);
    expect(screen.getAllByText('高/低')).toHaveLength(1);
    expect(screen.queryByText('Structured Market Data')).not.toBeInTheDocument();
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
    expect(screen.queryByText('Index')).not.toBeInTheDocument();
  });

  it('shows "No data" when breadth is not available for a market review payload', () => {
    render(
      <MarketReviewReportView
        payload={noBreadthMarketReviewPayload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Structured Market Data')).toBeInTheDocument();
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.getByText('S&P 500')).toBeInTheDocument();
    expect(screen.getAllByText('Industry Sectors').length).toBeGreaterThan(0);
    expect(screen.getByText('Technology')).toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.getAllByText('Macro Environment').length).toBeGreaterThan(0);
    expect(screen.getByText('10-Year Treasury Yield')).toBeInTheDocument();
    expect(screen.getByText('4.56%')).toBeInTheDocument();
    expect(screen.getByText('+0.02%')).toBeInTheDocument();
    expect(screen.getByText('2026-07-10')).toBeInTheDocument();
    expect(screen.getByText('FRED')).toBeInTheDocument();
    expect(screen.queryByText('Advancers')).not.toBeInTheDocument();
    expect(screen.queryByText('Decliners')).not.toBeInTheDocument();
  });

  it('hides limit up/down when the market review payload does not provide limit fields', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'zh',
      title: '美股大盘复盘',
      breadth: {
        upCount: 983,
        downCount: 913,
        flatCount: 104,
        totalAmount: 189727840037,
        turnoverUnit: 'USD',
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# 美股大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('上涨家数')).toBeInTheDocument();
    expect(screen.getByText('下跌家数')).toBeInTheDocument();
    expect(screen.queryByText('涨停/跌停')).not.toBeInTheDocument();
    expect(screen.getByText('成交额')).toBeInTheDocument();
  });

  it('formats structured market numbers to two decimal places', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: 4327,
        downCount: 1145,
        limitUpCount: 222,
        limitDownCount: 12,
        totalAmount: 3682249698199.88,
        turnoverUnit: 'CNY 100m',
      },
      indices: [{
        code: '000001',
        name: 'Shanghai Composite',
        current: 4112.446,
        changePct: 0.44079750937683315,
        high: 4143.314,
        low: 4087.54,
      }],
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('36822.50 CNY 100m')).toBeInTheDocument();
    expect(screen.getByText('4112.45')).toBeInTheDocument();
    expect(screen.getByText('0.44%')).toBeInTheDocument();
    expect(screen.getByText('4143.31 / 4087.54')).toBeInTheDocument();
    expect(screen.queryByText(/36822\.496/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.440797/)).not.toBeInTheDocument();
  });

  it('formats string-backed market numbers and hides missing high/low zeros', () => {
    const payload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: '4,327',
        downCount: '1,145',
        limitUpCount: '0',
        limitDownCount: '12',
        totalAmount: '3682249698199.88',
        turnoverUnit: 'CNY 100m',
      },
      indices: [{
        code: '000001',
        name: 'Shanghai Composite',
        current: '4,112.446',
        changePct: '0.44079750937683315%',
        high: 0,
        low: '0',
      }],
    } as unknown as MarketReviewPayload;

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('4327')).toBeInTheDocument();
    expect(screen.getByText('36822.50 CNY 100m')).toBeInTheDocument();
    expect(screen.getByText('4112.45')).toBeInTheDocument();
    expect(screen.getByText('0.44%')).toBeInTheDocument();
    expect(screen.queryByText('0.00 / 0.00')).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.440797/)).not.toBeInTheDocument();
  });

  it('scales raw USD turnover into USD 100m and shows Moomoo source/sample size', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'zh',
      title: '美股大盘复盘',
      rootTitle: '美股大盘复盘',
      breadth: {
        upCount: 983,
        downCount: 913,
        flatCount: 104,
        totalAmount: 189727840037,
        turnoverUnit: '亿美元',
        marketStatsSource: 'moomoo_us_exchange_universe',
        marketStatsSampleSize: 2000,
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# 美股大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('1897.28 亿美元')).toBeInTheDocument();
    expect(
      screen.getByText('来源：Moomoo · 覆盖样本：2,000 只'),
    ).toBeInTheDocument();
    expect(screen.queryByText('涨停/跌停')).not.toBeInTheDocument();
  });

  it('rejects US-only Moomoo breadth under A-shares and repairs its legacy US unit', () => {
    const market = (region: string, title: string): MarketReviewPayload => ({
      version: 1,
      kind: 'market_review',
      region,
      language: 'zh',
      title,
      breadth: {
        upCount: 819,
        downCount: 1063,
        totalAmount: 179599561831,
        turnoverUnit: '亿',
        marketStatsSource: 'moomoo_us_exchange_universe',
        marketStatsSampleSize: 2000,
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    });
    const payload: MarketReviewPayload = {
      ...market('cn,us', '大盘复盘'),
      markets: {
        cn: market('cn', 'A股大盘复盘'),
        us: market('us', '美股大盘复盘'),
      },
    };

    render(<MarketReviewReportView payload={payload} content="# 大盘复盘" reportLanguage="zh" />);

    expect(screen.queryByText('179599561831 亿')).not.toBeInTheDocument();
    expect(screen.queryByText('来源：Moomoo · 覆盖样本：2,000 只')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: '美股大盘复盘' }));
    expect(screen.getByText('1796.00 亿美元')).toBeInTheDocument();
    expect(screen.getByText('来源：Moomoo · 覆盖样本：2,000 只')).toBeInTheDocument();
  });

  it.each([
    ['cn', 'A股大盘复盘', '亿'],
    ['hk', '港股大盘复盘', '十亿港元'],
    ['us', '美股大盘复盘', '亿美元'],
    ['jp', '日股大盘复盘', '十亿日元'],
    ['kr', '韩股大盘复盘', '十亿韩元'],
  ])('derives the %s turnover unit when the payload omits it', (region, title, expectedUnit) => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region,
      language: 'zh',
      title,
      breadth: {
        upCount: 819,
        downCount: 1063,
        totalAmount: 179599561831,
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(<MarketReviewReportView payload={payload} content={`# ${title}`} reportLanguage="zh" />);

    if (region === 'cn') {
      expect(screen.getByText('1796.00 亿')).toBeInTheDocument();
    } else if (region === 'us') {
      expect(screen.getByText('1796.00 亿美元')).toBeInTheDocument();
    } else {
      expect(screen.getByText(`179.60 ${expectedUnit}`)).toBeInTheDocument();
    }
    expect(screen.queryByText('179599561831 亿')).not.toBeInTheDocument();
  });

  it('renders an unavailable NDX100 row without showing zero as a real index value', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'zh',
      title: '美股大盘复盘',
      indices: [{
        code: 'NDX100',
        name: '纳斯达克100指数',
        current: 0,
        changePct: 0,
        high: 0,
        low: 0,
        dataUnavailable: true,
        source: 'unavailable',
      }],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# 美股大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('数据暂不可用')).toBeInTheDocument();
    expect(screen.queryByText('0.00')).not.toBeInTheDocument();
    expect(screen.queryByText('0.00%')).not.toBeInTheDocument();
  });

  it('labels QQQ-backed NDX100 values as an ETF proxy', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'en',
      title: 'US Market Review',
      indices: [{
        code: 'NDX100',
        name: 'Nasdaq 100',
        current: 500,
        changePct: 1.1,
        proxy: true,
        source: 'nasdaq100_qqq_etf_proxy',
      }],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# US Market Review"
        reportLanguage="en"
      />,
    );

    const proxyLabel = screen.getByText('QQQ ETF Proxy');
    expect(proxyLabel).toBeInTheDocument();
    expect(proxyLabel).toHaveAttribute(
      'title',
      'Value is from QQQ, an ETF tracking the Nasdaq-100, not the official index level.',
    );
    expect(screen.getByText('500.00')).toBeInTheDocument();
  });

  it('renders unknown market_stats_source as 未标注 / Unknown (no raw id leak)', () => {
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: 100,
        downCount: 80,
        totalAmount: 1e11,
        turnoverUnit: 'USD bn',
        marketStatsSource: 'some_internal_secret_provider_xyz',
        marketStatsSampleSize: 500,
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Source: Unknown · Sample size: 500')).toBeInTheDocument();
    expect(screen.queryByText(/some_internal_secret_provider_xyz/)).not.toBeInTheDocument();
  });

  it('renders TickFlow / Yahoo Finance / Tushare as human readable names', () => {
    const cases = [
      { source: 'tickflow', expected: 'TickFlow' },
      { source: 'yfinance', expected: 'Yahoo Finance' },
      { source: 'tushare', expected: 'Tushare' },
    ];

    for (const c of cases) {
      const payload: MarketReviewPayload = {
        version: 1,
        kind: 'market_review',
        region: 'cn',
        language: 'zh',
        title: 'A股大盘复盘',
        rootTitle: 'A股大盘复盘',
        breadth: {
          upCount: 1,
          downCount: 1,
          totalAmount: 1e9,
          turnoverUnit: '亿元',
          marketStatsSource: c.source,
          marketStatsSampleSize: 100,
        },
        indices: [],
        sectors: { top: [], bottom: [] },
        concepts: { top: [], bottom: [] },
        news: [],
        sections: [],
        markdownReport: '',
      };

      const { unmount } = render(
        <MarketReviewReportView
          payload={payload}
          content="# A股大盘复盘"
          reportLanguage="zh"
        />,
      );

      expect(screen.getByText(`来源：${c.expected} · 覆盖样本：100 只`)).toBeInTheDocument();
      unmount();
    }
  });

  it('uses Breadth & Liquidity label and Rotation & Funds is gone', () => {
    const report: AnalysisReport = {
      meta: {
        queryId: 'market-review-q-us',
        stockCode: 'MARKET',
        stockName: 'Market Review',
        reportType: 'market_review',
        reportLanguage: 'en',
        createdAt: '2026-07-22T08:00:00Z',
      },
      summary: {
        analysisSummary: '',
        operationAdvice: 'breadth expanding, risk appetite recovering',
        trendPrediction: '',
        sentimentScore: 60,
      },
    };
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: 100,
        downCount: 80,
        totalAmount: 1e11,
        turnoverUnit: 'USD bn',
        marketStatsSource: 'moomoo_us_exchange_universe',
        marketStatsSampleSize: 2000,
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        report={report}
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Breadth & Liquidity')).toBeInTheDocument();
    expect(screen.queryByText('Rotation & Funds')).not.toBeInTheDocument();
    expect(screen.getByText('Source: Moomoo · Sample size: 2,000')).toBeInTheDocument();
  });

  it('uses Rotation & Funds label when payload.region is cn (zh)', () => {
    const report: AnalysisReport = {
      meta: {
        queryId: 'market-review-q-cn',
        stockCode: 'MARKET',
        stockName: '大盘复盘',
        reportType: 'market_review',
        reportLanguage: 'zh',
        createdAt: '2026-07-22T08:00:00Z',
      },
      summary: {
        analysisSummary: '',
        operationAdvice: '主线切换至科技板块',
        trendPrediction: '',
        sentimentScore: 55,
      },
    };
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'zh',
      title: 'A股大盘复盘',
      rootTitle: 'A股大盘复盘',
      breadth: {
        upCount: 3500,
        downCount: 1500,
        flatCount: 200,
        limitUpCount: 80,
        limitDownCount: 5,
        totalAmount: 9.8e11,
        turnoverUnit: '亿元',
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        report={report}
        payload={payload}
        content="# A股大盘复盘"
        reportLanguage="zh"
      />,
    );

    expect(screen.getByText('轮动与资金')).toBeInTheDocument();
    expect(screen.queryByText('市场宽度与流动性')).not.toBeInTheDocument();
  });

  it('uses Rotation & Funds label when payload.region is cn (en)', () => {
    const report: AnalysisReport = {
      meta: {
        queryId: 'market-review-q-cn-en',
        stockCode: 'MARKET',
        stockName: 'Market Review',
        reportType: 'market_review',
        reportLanguage: 'en',
        createdAt: '2026-07-22T08:00:00Z',
      },
      summary: {
        analysisSummary: '',
        operationAdvice: 'rotation into tech',
        trendPrediction: '',
        sentimentScore: 55,
      },
    };
    const payload: MarketReviewPayload = {
      version: 1,
      kind: 'market_review',
      region: 'cn',
      language: 'en',
      title: 'Market Review',
      rootTitle: 'Market Review',
      breadth: {
        upCount: 100,
        downCount: 80,
        totalAmount: 1e12,
        turnoverUnit: 'CNY 100m',
      },
      indices: [],
      sectors: { top: [], bottom: [] },
      concepts: { top: [], bottom: [] },
      news: [],
      sections: [],
      markdownReport: '',
    };

    render(
      <MarketReviewReportView
        report={report}
        payload={payload}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Rotation & Funds')).toBeInTheDocument();
    expect(screen.queryByText('Breadth & Liquidity')).not.toBeInTheDocument();
  });

  it('falls back to Breadth & Liquidity when payload.region is missing', () => {
    const report: AnalysisReport = {
      meta: {
        queryId: 'market-review-q-fallback',
        stockCode: 'MARKET',
        stockName: 'Market Review',
        reportType: 'market_review',
        reportLanguage: 'en',
        createdAt: '2026-07-22T08:00:00Z',
      },
      summary: {
        analysisSummary: '',
        operationAdvice: '...',
        trendPrediction: '',
        sentimentScore: undefined as unknown as number,
      },
    };

    render(
      <MarketReviewReportView
        report={report}
        content="# Market Review"
        reportLanguage="en"
      />,
    );

    expect(screen.getByText('Breadth & Liquidity')).toBeInTheDocument();
    expect(screen.queryByText('Rotation & Funds')).not.toBeInTheDocument();
  });

  it('opens run flow for historical market review records', () => {
    const onOpenRunFlow = vi.fn();

    render(
      <MarketReviewReportView
        payload={combinedMarketReviewPayload}
        content="# 大盘复盘"
        recordId={7}
        reportLanguage="zh"
        onOpenRunFlow={onOpenRunFlow}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '查看历史记录 7 运行流' }));

    expect(onOpenRunFlow).toHaveBeenCalledWith(7);
  });
});
