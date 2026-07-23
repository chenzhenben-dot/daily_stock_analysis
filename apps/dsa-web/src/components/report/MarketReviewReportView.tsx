import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, Clipboard, FileText, Gauge, Layers, ShieldAlert, TrendingUp, WalletCards, Workflow } from 'lucide-react';
import { historyApi } from '../../api/history';
import { formatUiText, UI_TEXT } from '../../i18n/uiText';
import type {
  AnalysisReport,
  MarketReviewPayload,
  MarketReviewPayloadSection,
  ReportLanguage,
} from '../../types/analysis';
import { markdownToPlainText } from '../../utils/markdown';
import { getReportText, normalizeReportLanguage } from '../../utils/reportLanguage';
import { Card } from '../common';
import { Tooltip } from '../common/Tooltip';
import { ReportMarkdownBody } from './ReportMarkdownBody';

interface MarketReviewReportViewProps {
  report?: AnalysisReport;
  recordId?: number;
  content?: string;
  payload?: MarketReviewPayload | null;
  reportLanguage?: ReportLanguage;
  className?: string;
  onOpenRunFlow?: (recordId: number) => void;
}

type CopyType = 'markdown' | 'text';
type LoadedMarkdown = {
  recordId: number;
  content: string;
};
type LoadError = {
  recordId: number;
  message: string;
};
type MarketReviewSection = {
  id: string;
  title: string;
  content: string;
  icon: typeof FileText;
};
type StructuredMarketData = {
  id: string;
  title?: string;
  breadth?: MarketReviewPayload['breadth'];
  indices: NonNullable<MarketReviewPayload['indices']>;
  sectors?: MarketReviewPayload['sectors'];
  concepts?: MarketReviewPayload['concepts'];
  macro?: MarketReviewPayload['macro'];
};

const isMarketReviewPayload = (value: unknown): value is MarketReviewPayload =>
  Boolean(value && typeof value === 'object');

const TOP_HEADING_PATTERN = /^\s*#\s+(.+?)\s*(?:\n+|$)/;
const SECTION_HEADING_PATTERN = /^(#{2,3})\s+(.+?)\s*$/gm;

const normalizeHeading = (value: string): string =>
  value.trim().replace(/\s+/g, ' ').toLowerCase();

const stripTopHeading = (markdown: string, title?: string): string => {
  const match = markdown.match(TOP_HEADING_PATTERN);
  if (!match) {
    return markdown.trim();
  }

  const heading = normalizeHeading(match[1]);
  const reportTitle = normalizeHeading(title || '');
  const genericTitles = new Set([
    'market review',
    '大盘复盘',
    '大盘复盘详情',
    'a股市场复盘',
    'a 股市场复盘',
  ]);

  if (heading === reportTitle || genericTitles.has(heading)) {
    return markdown.slice(match[0].length).trim();
  }

  return markdown.trim();
};

const getSectionIcon = (title: string): typeof FileText => {
  const normalized = normalizeHeading(title);
  if (/指数|index|overview|大盘/.test(normalized)) {
    return BarChart3;
  }
  if (/情绪|赚钱|sentiment|breadth|temperature/.test(normalized)) {
    return Gauge;
  }
  if (/行业|板块|主题|轮动|sector|theme|rotation/.test(normalized)) {
    return TrendingUp;
  }
  if (/资金|成交|量能|flow|turnover|volume|capital/.test(normalized)) {
    return WalletCards;
  }
  if (/风险|机会|观察|risk|watch|next/.test(normalized)) {
    return ShieldAlert;
  }
  return FileText;
};

const splitMarketReviewSections = (markdown: string): MarketReviewSection[] => {
  const matches = Array.from(markdown.matchAll(SECTION_HEADING_PATTERN));
  if (matches.length === 0) {
    return [{
      id: 'full-review',
      title: '复盘正文',
      content: markdown,
      icon: FileText,
    }];
  }

  const intro = markdown.slice(0, matches[0].index).trim();
  const sections: MarketReviewSection[] = intro
    ? [{
        id: 'overview',
        title: '复盘概览',
        content: intro,
        icon: FileText,
      }]
    : [];

  matches.forEach((match, index) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index ?? markdown.length : markdown.length;
    const title = match[2].trim();
    const content = markdown.slice(start, end).trim();
    if (!content) {
      return;
    }
    sections.push({
      id: `${index}-${normalizeHeading(title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-').replace(/^-|-$/g, '') || 'section'}`,
      title,
      content,
      icon: getSectionIcon(title),
    });
  });

  return sections;
};

const getPayloadSections = (payload?: MarketReviewPayload | null): MarketReviewSection[] => {
  if (!payload) {
    return [];
  }

  if (payload.markets) {
    return Object.entries(payload.markets).flatMap(([region, marketPayload]) => {
      const marketTitle = marketPayload.title || region.toUpperCase();
      return getPayloadSections(marketPayload).map((section) => ({
        ...section,
        id: `${region}-${section.id}`,
        title: `${marketTitle} / ${section.title}`,
      }));
    });
  }

  const payloadTitle = normalizeHeading(payload.title || '');
  return (payload.sections || [])
    .filter((section: MarketReviewPayloadSection) => section.markdown?.trim())
    .filter((section: MarketReviewPayloadSection) => normalizeHeading(section.title || '') !== payloadTitle)
    .map((section, index) => ({
      id: `${section.key || index}-${normalizeHeading(section.title).replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-') || 'section'}`,
      title: section.title || 'Review',
      content: section.markdown,
      icon: getSectionIcon(section.title || ''),
    }));
};

const hasRankingRows = (rankings?: MarketReviewPayload['sectors']): boolean =>
  Boolean(rankings?.top?.length || rankings?.bottom?.length);

const hasStructuredMarketData = (payload?: MarketReviewPayload | null): boolean =>
  Boolean(payload?.breadth || payload?.indices?.length || payload?.macro?.length
    || hasRankingRows(payload?.sectors) || hasRankingRows(payload?.concepts));

const normalizeBreadthForRegion = (
  breadth: MarketReviewPayload['breadth'],
  region: string,
  language?: string,
): MarketReviewPayload['breadth'] => {
  if (!breadth) return undefined;

  const source = breadth.marketStatsSource || '';
  const isMoomooUsStats = source.startsWith('moomoo_');
  if (isMoomooUsStats && region !== 'us') {
    return undefined;
  }

  const unit = breadth.turnoverUnit;
  if (isMoomooUsStats && region === 'us' && ['亿', '亿元', 'CNY 100m'].includes(unit || '')) {
    return {
      ...breadth,
      turnoverUnit: language === 'en' ? 'USD 100m' : '亿美元',
    };
  }
  return breadth;
};

const getStructuredMarketData = (payload?: MarketReviewPayload | null): StructuredMarketData[] => {
  if (!payload) {
    return [];
  }

  if (payload.markets) {
    return Object.entries(payload.markets)
      .filter(([, marketPayload]) => hasStructuredMarketData(marketPayload))
      .map(([region, marketPayload]) => ({
        id: region,
        title: marketPayload.title || region.toUpperCase(),
        breadth: normalizeBreadthForRegion(marketPayload.breadth, region, marketPayload.language),
        indices: marketPayload.indices || [],
        sectors: marketPayload.sectors,
        concepts: marketPayload.concepts,
        macro: marketPayload.macro,
      }));
  }

  if (!hasStructuredMarketData(payload)) {
    return [];
  }

  return [{
    id: payload.region || 'market',
    title: payload.title,
    breadth: normalizeBreadthForRegion(payload.breadth, payload.region || 'market', payload.language),
    indices: payload.indices || [],
    sectors: payload.sectors,
    concepts: payload.concepts,
    macro: payload.macro,
  }];
};

const coerceFiniteNumber = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }

  if (typeof value === 'string' && value.trim()) {
    const normalizedValue = value.trim().replace(/,/g, '');
    const numericText = normalizedValue.endsWith('%')
      ? normalizedValue.slice(0, -1).trim()
      : normalizedValue;
    const parsed = Number(numericText);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

const formatMarketNumber = (value: unknown, options?: { zeroAsMissing?: boolean }): string => {
  const numericValue = coerceFiniteNumber(value);
  if (numericValue === null || (options?.zeroAsMissing && numericValue === 0)) {
    return '-';
  }
  return numericValue.toFixed(2);
};

const formatMarketCount = (value: unknown): string => {
  const numericValue = coerceFiniteNumber(value);
  return numericValue === null ? '-' : numericValue.toFixed(0);
};

const formatMarketAmount = (value: unknown, unit?: string): string => {
  const numericValue = coerceFiniteNumber(value);
  if (numericValue === null) {
    return '-';
  }
  if (!unit) {
    return numericValue.toFixed(0);
  }
  // Backend stores raw turnover; UI scales according to the explicit unit.
  // New US payloads use USD 100m / 亿美元. Keep USD bn / 十亿美元 support
  // so historical reports continue to render with their original scale.
  const isUsdHundredMillion =
    unit.startsWith('USD 100m') ||
    unit === '亿美元';
  if (isUsdHundredMillion) {
    return `${(numericValue / 1e8).toFixed(2)} ${unit}`;
  }
  const isLocalCurrencyBillion =
    unit.startsWith('USD bn') ||
    unit.startsWith('HKD bn') ||
    unit.startsWith('JPY bn') ||
    unit.startsWith('KRW bn') ||
    unit === '十亿美元' ||
    unit === '十亿港元' ||
    unit === '十亿日元' ||
    unit === '十亿韩元';
  if (isLocalCurrencyBillion) {
    return `${(numericValue / 1e9).toFixed(2)} ${unit}`;
  }
  // Fallback (e.g. CNY 100m / 亿元): render the value as-is, scaled by 1e8 when
  // the backend has already provided raw CNY.
  if (numericValue > 1e6 && (unit === '亿元' || unit === 'CNY 100m')) {
    return `${(numericValue / 1e8).toFixed(2)} ${unit}`;
  }
  return `${numericValue.toFixed(0)} ${unit}`;
};

const formatMarketPercent = (value: unknown): string => {
  const formattedValue = formatMarketNumber(value);
  return formattedValue === '-' ? '-' : `${formattedValue}%`;
};

const formatMarketHighLow = (high: unknown, low: unknown): string => {
  const highText = formatMarketNumber(high, { zeroAsMissing: true });
  const lowText = formatMarketNumber(low, { zeroAsMissing: true });
  return highText === '-' && lowText === '-' ? '-' : `${highText} / ${lowText}`;
};

type MarketReviewTextBundle = (typeof MARKET_REVIEW_TEXT)[ReportLanguage];

/**
 * 用户可读的 source label 映射。
 * 原始 source id（payload.market_stats_source）保留在 payload 中，但主界面文字
 * 应展示为这些人类可读的名字，避免用户看到 `moomoo_us_exchange_universe` 这种
 * 内部实现细节。
 */
const MARKET_STATS_SOURCE_LABELS: Record<string, { zh: string; en: string; ko: string }> = {
  moomoo_us_exchange_universe: { zh: 'Moomoo', en: 'Moomoo', ko: 'Moomoo' },
  moomoo_large_cap_sample: { zh: 'Moomoo', en: 'Moomoo', ko: 'Moomoo' },
  tickflow: { zh: 'TickFlow', en: 'TickFlow', ko: 'TickFlow' },
  akshare: { zh: 'AkShare', en: 'AkShare', ko: 'AkShare' },
  tushare: { zh: 'Tushare', en: 'Tushare', ko: 'Tushare' },
  efinance: { zh: 'eFinance', en: 'eFinance', ko: 'eFinance' },
  yfinance: { zh: 'Yahoo Finance', en: 'Yahoo Finance', ko: 'Yahoo Finance' },
};

const formatSourceLabel = (rawSource: string | undefined, reportLanguage: ReportLanguage): string => {
  if (!rawSource) {
    return reportLanguage === 'en' ? 'Unknown' : reportLanguage === 'ko' ? '미표기' : '未标注';
  }
  const mapped = MARKET_STATS_SOURCE_LABELS[rawSource];
  if (mapped) {
    return mapped[reportLanguage];
  }
  // 未识别的 source id 不直接渲染到主界面，避免泄露内部实现
  return reportLanguage === 'en' ? 'Unknown' : reportLanguage === 'ko' ? '기타' : '未标注';
};

const REGION_ROTATION_OVERRIDES: Record<
  ReportLanguage,
  { rotationAndFunds: string; noRotationView: string }
> = {
  zh: {
    rotationAndFunds: '轮动与资金',
    noRotationView: '暂无轮动与资金观点',
  },
  en: {
    rotationAndFunds: 'Rotation & Funds',
    noRotationView: 'No rotation/funds view yet',
  },
  ko: {
    rotationAndFunds: '순환과 자금',
    noRotationView: '순환/자금 관점 없음',
  },
};

const isCnRegion = (region: string | undefined): boolean => {
  if (!region) return false;
  return region
    .split(',')
    .map((part) => part.trim().toLowerCase())
    .some((part) => part === 'cn' || part === 'a' || part === 'a-share' || part.startsWith('cn-'));
};

/**
 * 按 payload.region 决定 rotationAndFunds / noRotationView 文案。
 * - cn：保留"轮动与资金 / Rotation & Funds"（CN 拥有真实资金流数据）。
 * - us / hk / jp / kr：默认已是"市场宽度与流动性 / Breadth & Liquidity"，
 *   因为这些市场没有 ETF 资金流 / 交易所净流入 / 机构资金数据，
 *   渲染"资金流"会引导 LLM / 用户误解为有真实资金流统计。
 * - 其他 / 缺省：fallback 到语言对应的默认文案（= 宽度与流动性）。
 */
const resolveRotationLabels = (
  base: MarketReviewTextBundle,
  region: string | undefined,
  reportLanguage: ReportLanguage,
): Pick<MarketReviewTextBundle, 'rotationAndFunds' | 'noRotationView'> => {
  if (isCnRegion(region)) {
    return REGION_ROTATION_OVERRIDES[reportLanguage];
  }
  return {
    rotationAndFunds: base.rotationAndFunds,
    noRotationView: base.noRotationView,
  };
};

const MARKET_REVIEW_TEXT: Record<ReportLanguage, {
  reviewSummary: string;
  noReviewSummary: string;
  noSentimentScore: string;
  rotationAndFunds: string;
  noRotationView: string;
  riskAndWatch: string;
  noRiskWatch: string;
  structuredMarketData: string;
  noBreadthData: string;
  advancers: string;
  decliners: string;
  limitUpDown: string;
  turnover: string;
  sourceNote: string;
  index: string;
  last: string;
  change: string;
  highLow: string;
  industryBoards: string;
  conceptBoards: string;
  leading: string;
  lagging: string;
  macroIndicators: string;
  macroValue: string;
  macroChange: string;
  asOf: string;
  source: string;
  dataUnavailable: string;
  qqqProxy: string;
  qqqProxyTooltip: string;
}> = {
  zh: {
    reviewSummary: '复盘摘要',
    noReviewSummary: '暂无摘要',
    noSentimentScore: '暂无评分',
    rotationAndFunds: '市场宽度与流动性',
    noRotationView: '暂无宽度与流动性观点',
    riskAndWatch: '风险与观察',
    noRiskWatch: '暂无观察重点',
    structuredMarketData: '结构化大盘数据',
    noBreadthData: '暂无数据',
    advancers: '上涨家数',
    decliners: '下跌家数',
    limitUpDown: '涨停/跌停',
    turnover: '成交额',
    sourceNote: '来源：{source} · 覆盖样本：{sample} 只',
    index: '指数',
    last: '最新',
    change: '涨跌幅',
    highLow: '高/低',
    industryBoards: '行业板块',
    conceptBoards: '概念板块',
    leading: '领涨',
    lagging: '领跌',
    macroIndicators: '宏观环境',
    macroValue: '最新值',
    macroChange: '较前值',
    asOf: '数据日期',
    source: '来源',
    dataUnavailable: '数据暂不可用',
    qqqProxy: 'QQQ ETF 代理',
    qqqProxyTooltip: '该数值来自追踪纳斯达克100的 QQQ ETF，并非官方指数点位。',
  },
  en: {
    reviewSummary: 'Review Summary',
    noReviewSummary: 'No review summary yet',
    noSentimentScore: 'No score yet',
    rotationAndFunds: 'Breadth & Liquidity',
    noRotationView: 'No breadth/liquidity view yet',
    riskAndWatch: 'Risks & Watchlist',
    noRiskWatch: 'No key observations yet',
    structuredMarketData: 'Structured Market Data',
    noBreadthData: 'No data',
    advancers: 'Advancers',
    decliners: 'Decliners',
    limitUpDown: 'Limit Up/Down',
    turnover: 'Turnover',
    sourceNote: 'Source: {source} · Sample size: {sample}',
    index: 'Index',
    last: 'Last',
    change: 'Change',
    highLow: 'High/Low',
    industryBoards: 'Industry Sectors',
    conceptBoards: 'Concept Themes',
    leading: 'Leading',
    lagging: 'Lagging',
    macroIndicators: 'Macro Environment',
    macroValue: 'Latest',
    macroChange: 'Change',
    asOf: 'As of',
    source: 'Source',
    dataUnavailable: 'Data unavailable',
    qqqProxy: 'QQQ ETF Proxy',
    qqqProxyTooltip: 'Value is from QQQ, an ETF tracking the Nasdaq-100, not the official index level.',
  },
  ko: {
    reviewSummary: '리뷰 요약',
    noReviewSummary: '요약 없음',
    noSentimentScore: '점수 없음',
    rotationAndFunds: '시장 폭과 유동성',
    noRotationView: '폭/유동성 관점 없음',
    riskAndWatch: '리스크와 관찰',
    noRiskWatch: '관찰 포인트 없음',
    structuredMarketData: '구조화 시장 데이터',
    noBreadthData: '데이터 없음',
    advancers: '상승 종목 수',
    decliners: '하락 종목 수',
    limitUpDown: '상한가/하한가',
    turnover: '거래대금',
    sourceNote: '출처: {source} · 표본 크기: {sample}',
    index: '지수',
    last: '현재',
    change: '등락률',
    highLow: '고가/저가',
    industryBoards: '업종 섹터',
    conceptBoards: '테마 섹터',
    leading: '강세',
    lagging: '약세',
    macroIndicators: '거시 환경',
    macroValue: '최신값',
    macroChange: '이전 대비',
    asOf: '기준일',
    source: '출처',
    dataUnavailable: '데이터 없음',
    qqqProxy: 'QQQ ETF 대체 데이터',
    qqqProxyTooltip: '이 값은 공식 지수 값이 아니라 나스닥 100을 추종하는 QQQ ETF에서 가져왔습니다.',
  },
};

const formatRankingChange = (value: unknown): string => {
  const numeric = typeof value === 'number' ? value : Number(String(value ?? '').replace(/%$/, ''));
  if (!Number.isFinite(numeric)) {
    return '-';
  }
  const sign = numeric > 0 ? '+' : '';
  return `${sign}${numeric.toFixed(2)}%`;
};

const formatMacroNumber = (value: unknown, unit?: string, signed = false): string => {
  const numeric = coerceFiniteNumber(value);
  if (numeric === null) {
    return '-';
  }
  const sign = signed && numeric > 0 ? '+' : '';
  const suffix = unit === '%' ? '%' : unit ? ` ${unit}` : '';
  return `${sign}${numeric.toFixed(2)}${suffix}`;
};

export const MarketReviewReportView: React.FC<MarketReviewReportViewProps> = ({
  report,
  recordId,
  content: providedContent,
  payload: providedPayload,
  reportLanguage = 'zh',
  className = '',
  onOpenRunFlow,
}) => {
  const normalizedReportLanguage = normalizeReportLanguage(reportLanguage);
  const text = getReportText(normalizedReportLanguage);
  const runFlowText = UI_TEXT[normalizedReportLanguage === 'ko' ? 'en' : normalizedReportLanguage];
  const marketReviewText = MARKET_REVIEW_TEXT[normalizedReportLanguage];
  const [loadedMarkdown, setLoadedMarkdown] = useState<LoadedMarkdown | null>(null);
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [copiedType, setCopiedType] = useState<CopyType | null>(null);
  const summary = report?.summary;
  const meta = report?.meta;
  const contextPayload = report?.details?.contextSnapshot?.marketReviewPayload;
  const marketReviewPayload = providedPayload ?? (isMarketReviewPayload(contextPayload) ? contextPayload : null);
  // rotationAndFunds 文案按 payload.region 分流：
  // cn 保留"轮动与资金"，其他市场默认显示"市场宽度与流动性"。
  const rotationLabels = useMemo(
    () => resolveRotationLabels(marketReviewText, marketReviewPayload?.region, normalizedReportLanguage),
    [marketReviewText, marketReviewPayload?.region, normalizedReportLanguage],
  );
  const loadedContent = loadedMarkdown && loadedMarkdown.recordId === recordId ? loadedMarkdown.content : '';
  const content = providedContent ?? marketReviewPayload?.markdownReport ?? loadedContent;
  const error = loadError && loadError.recordId === recordId ? loadError.message : null;
  const hasStructuredContent = Boolean(marketReviewPayload?.sections?.length || marketReviewPayload?.markets);
  const isLoading = Boolean(recordId && !providedContent && !hasStructuredContent && loadedMarkdown?.recordId !== recordId && !error);
  const displayTitle = marketReviewPayload?.rootTitle || marketReviewPayload?.title || meta?.stockName || 'Market Review';
  const structuredContent = useMemo(
    () => stripTopHeading(content, displayTitle),
    [content, displayTitle],
  );
  const sections = useMemo(
    () => {
      const payloadSections = getPayloadSections(marketReviewPayload);
      return payloadSections.length > 0 ? payloadSections : splitMarketReviewSections(structuredContent);
    },
    [marketReviewPayload, structuredContent],
  );
  const structuredMarketData = useMemo(
    () => getStructuredMarketData(marketReviewPayload),
    [marketReviewPayload],
  );
  const showStructuredMarketTitles = Boolean(marketReviewPayload?.markets);
  const [activeMarketId, setActiveMarketId] = useState<string | null>(null);
  const showMarketTabBar = Boolean(marketReviewPayload?.markets && structuredMarketData.length > 1);

  useEffect(() => {
    if (!showMarketTabBar) {
      if (activeMarketId !== null) {
        setActiveMarketId(null);
      }
      return;
    }
    if (structuredMarketData.length === 0) {
      if (activeMarketId !== null) {
        setActiveMarketId(null);
      }
      return;
    }
    if (!activeMarketId || !structuredMarketData.some((m) => m.id === activeMarketId)) {
      setActiveMarketId(structuredMarketData[0].id);
    }
  }, [structuredMarketData, showMarketTabBar, activeMarketId]);

  const activeMarketData = activeMarketId
    ? structuredMarketData.find((m) => m.id === activeMarketId) ?? null
    : (showMarketTabBar ? null : (structuredMarketData[0] ?? null));

  const sectionsByMarket = useMemo(() => {
    const all = getPayloadSections(marketReviewPayload);
    if (!showMarketTabBar || !activeMarketId) return all;
    const prefix = `${activeMarketId}-`;
    return all
      .filter((s) => s.id.startsWith(prefix))
      .map((s) => ({ ...s, id: s.id.slice(prefix.length) }));
  }, [marketReviewPayload, showMarketTabBar, activeMarketId]);

  const effectiveSections = sectionsByMarket.length > 0 ? sectionsByMarket : sections;
  const canOpenRunFlow = recordId !== undefined && onOpenRunFlow;

  useEffect(() => {
    if (!recordId || providedContent || hasStructuredContent) {
      return undefined;
    }

    let isMounted = true;

    historyApi.getMarkdown(recordId)
      .then((markdownContent) => {
        if (isMounted) {
          setLoadedMarkdown({ recordId, content: markdownContent });
          setLoadError(null);
        }
      })
      .catch((err: unknown) => {
        if (isMounted) {
          setLoadError({
            recordId,
            message: err instanceof Error ? err.message : text.loadReportFailed,
          });
        }
      });

    return () => {
      isMounted = false;
    };
  }, [hasStructuredContent, providedContent, recordId, text.loadReportFailed]);

  const handleCopy = useCallback(async (type: CopyType) => {
    if (!content) {
      return;
    }
    try {
      const value = type === 'markdown' ? content : markdownToPlainText(content);
      await navigator.clipboard.writeText(value);
      setCopiedType(type);
      window.setTimeout(() => setCopiedType(null), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  }, [content]);

  const insightCards = useMemo(() => [
    {
      icon: FileText,
      label: marketReviewText.reviewSummary,
      value: summary?.analysisSummary || marketReviewText.noReviewSummary,
    },
    {
      icon: Gauge,
      label: text.marketSentiment,
      value: summary?.sentimentScore !== undefined
        ? `${summary.sentimentScore} / 100`
        : marketReviewText.noSentimentScore,
    },
    {
      icon: Layers,
      label: rotationLabels.rotationAndFunds,
      value: summary?.operationAdvice || rotationLabels.noRotationView,
    },
    {
      icon: ShieldAlert,
      label: marketReviewText.riskAndWatch,
      value: summary?.trendPrediction || marketReviewText.noRiskWatch,
    },
  ], [marketReviewText, rotationLabels, summary, text.marketSentiment]);

  return (
    <div className={`animate-fade-in space-y-4 pb-8 ${className}`}>
      <Card variant="gradient" padding="md" className="home-report-hero text-left">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="mb-2 inline-flex items-center gap-2 text-xs font-semibold text-secondary-text">
              <BarChart3 className="h-4 w-4" aria-hidden="true" />
              <span>MARKET REVIEW</span>
            </div>
            <h2 className="text-[26px] font-bold leading-tight text-foreground sm:text-[30px]">
              {displayTitle}
            </h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-text">
              {meta?.stockCode ? (
                <span className="home-accent-chip px-2 py-0.5 font-mono">{meta.stockCode}</span>
              ) : null}
              {meta?.createdAt ? <span>{new Date(meta.createdAt).toLocaleString()}</span> : null}
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {canOpenRunFlow ? (
              <Tooltip content={runFlowText['runFlow.open']}>
                <span className="inline-flex">
                  <button
                    type="button"
                    onClick={() => onOpenRunFlow(recordId)}
                    className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground"
                    aria-label={formatUiText(runFlowText['runFlow.openHistoryAria'], { recordId })}
                  >
                    <Workflow className="h-5 w-5" aria-hidden="true" />
                  </button>
                </span>
              </Tooltip>
            ) : null}
            <Tooltip content={text.copyMarkdownSource}>
              <span className="inline-flex">
                <button
                  type="button"
                  onClick={() => void handleCopy('markdown')}
                  disabled={isLoading || !content || copiedType !== null}
                  className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
                  aria-label={text.copyMarkdownSource}
                >
                  {copiedType === 'markdown' ? (
                    <svg className="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <Clipboard className="h-5 w-5" aria-hidden="true" />
                  )}
                </button>
              </span>
            </Tooltip>
            <Tooltip content={text.copyPlainText}>
              <span className="inline-flex">
                <button
                  type="button"
                  onClick={() => void handleCopy('text')}
                  disabled={isLoading || !content || copiedType !== null}
                  className="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
                  aria-label={text.copyPlainText}
                >
                  {copiedType === 'text' ? (
                    <svg className="h-5 w-5 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <FileText className="h-5 w-5" aria-hidden="true" />
                  )}
                </button>
              </span>
            </Tooltip>
          </div>
        </div>
      </Card>

      {summary ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          {insightCards.map(({ icon: Icon, label, value }) => (
            <Card key={label} variant="bordered" padding="sm" className="home-panel-card text-left">
              <div className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p className="label-uppercase">{label}</p>
                  <p className="mt-2 line-clamp-4 text-sm leading-6 text-foreground">{value}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}

      {structuredMarketData.length > 0 ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="mb-3 flex items-center gap-3 overflow-x-auto pb-1">
            <div className="flex shrink-0 items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <BarChart3 className="h-4 w-4" aria-hidden="true" />
              </span>
              <h3 className="text-base font-semibold text-foreground">{marketReviewText.structuredMarketData}</h3>
            </div>
            {showMarketTabBar ? (
              <div className="flex shrink-0 flex-nowrap gap-1.5" role="tablist" aria-label={marketReviewText.structuredMarketData}>
                {structuredMarketData.map((market) => {
                  const isActive = market.id === activeMarketId;
                  return (
                    <button
                      key={market.id}
                      role="tab"
                      aria-selected={isActive}
                      type="button"
                      onClick={() => setActiveMarketId(market.id)}
                      className={
                        isActive
                          ? 'whitespace-nowrap rounded-md border border-primary/60 bg-primary/15 px-3 py-1.5 text-xs font-medium text-primary transition-colors'
                          : 'whitespace-nowrap rounded-md border border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-secondary-text transition-colors hover:bg-secondary/40'
                      }
                    >
                      {market.title}
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>
          <div className="space-y-5">
            {activeMarketData ? (
              <div key={activeMarketData.id} className="space-y-3">
                {(showStructuredMarketTitles || showMarketTabBar) && activeMarketData.title ? (
                  <h4 className="text-sm font-semibold text-foreground">{activeMarketData.title}</h4>
                ) : null}
                {activeMarketData.breadth ? (
                  <div className="space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                      <div className="rounded-lg border border-subtle p-3">
                        <p className="label-uppercase">{marketReviewText.advancers}</p>
                        <p className="mt-1 font-semibold text-foreground">
                          {formatMarketCount(activeMarketData.breadth.upCount)}
                        </p>
                      </div>
                      <div className="rounded-lg border border-subtle p-3">
                        <p className="label-uppercase">{marketReviewText.decliners}</p>
                        <p className="mt-1 font-semibold text-foreground">
                          {formatMarketCount(activeMarketData.breadth.downCount)}
                        </p>
                      </div>
                      {activeMarketData.breadth.limitUpCount !== undefined || activeMarketData.breadth.limitDownCount !== undefined ? (
                        <div className="rounded-lg border border-subtle p-3">
                          <p className="label-uppercase">{marketReviewText.limitUpDown}</p>
                          <p className="mt-1 font-semibold text-foreground">
                            {formatMarketCount(activeMarketData.breadth.limitUpCount)} /{' '}
                            {formatMarketCount(activeMarketData.breadth.limitDownCount)}
                          </p>
                        </div>
                      ) : null}
                      <div className="rounded-lg border border-subtle p-3">
                        <p className="label-uppercase">{marketReviewText.turnover}</p>
                        <p className="mt-1 font-semibold text-foreground">
                          {formatMarketAmount(activeMarketData.breadth.totalAmount, activeMarketData.breadth.turnoverUnit)}
                        </p>
                      </div>
                    </div>
                    {activeMarketData.breadth.marketStatsSource || activeMarketData.breadth.marketStatsSampleSize ? (
                      <p className="text-xs text-secondary-text">
                        {marketReviewText.sourceNote
                          .replace('{source}', formatSourceLabel(activeMarketData.breadth.marketStatsSource, normalizedReportLanguage))
                          .replace(
                            '{sample}',
                            activeMarketData.breadth.marketStatsSampleSize
                              ? activeMarketData.breadth.marketStatsSampleSize.toLocaleString('zh-CN')
                              : '—',
                          )}
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="text-sm text-secondary-text">{marketReviewText.noBreadthData}</p>
                )}
                {activeMarketData.indices.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-sm">
                      <thead className="text-left text-xs uppercase text-muted-text">
                        <tr>
                          <th className="px-2 py-2">{marketReviewText.index}</th>
                          <th className="px-2 py-2">{marketReviewText.last}</th>
                          <th className="px-2 py-2">{marketReviewText.change}</th>
                          <th className="px-2 py-2">{marketReviewText.highLow}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-subtle">
                        {activeMarketData.indices.map((index) => {
                          const unavailable = index.dataUnavailable === true;
                          return (
                            <tr key={index.code || index.name}>
                              <td className="px-2 py-2 font-medium text-foreground">
                                <span className="inline-flex flex-wrap items-center gap-2">
                                  <span>{index.name}</span>
                                  {index.proxy ? (
                                    <span
                                      className="rounded border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
                                      title={marketReviewText.qqqProxyTooltip}
                                    >
                                      {marketReviewText.qqqProxy}
                                    </span>
                                  ) : null}
                                </span>
                              </td>
                              <td className="px-2 py-2 text-secondary-text">
                                {unavailable ? marketReviewText.dataUnavailable : formatMarketNumber(index.current)}
                              </td>
                              <td className="px-2 py-2 text-secondary-text">
                                {unavailable ? '-' : formatMarketPercent(index.changePct)}
                              </td>
                              <td className="px-2 py-2 text-secondary-text">
                                {unavailable ? '-' : formatMarketHighLow(index.high, index.low)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {activeMarketData.macro?.length ? (
                  <div className="overflow-x-auto">
                    <p className="label-uppercase mb-2">{marketReviewText.macroIndicators}</p>
                    <table className="min-w-full text-sm">
                      <thead className="text-left text-xs uppercase text-muted-text">
                        <tr>
                          <th className="px-2 py-2">{marketReviewText.macroIndicators}</th>
                          <th className="px-2 py-2">{marketReviewText.macroValue}</th>
                          <th className="px-2 py-2">{marketReviewText.macroChange}</th>
                          <th className="px-2 py-2">{marketReviewText.asOf}</th>
                          <th className="px-2 py-2">{marketReviewText.source}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-subtle">
                        {activeMarketData.macro.map((indicator) => (
                          <tr key={indicator.seriesId}>
                            <td className="px-2 py-2 font-medium text-foreground">
                              {normalizedReportLanguage === 'zh'
                                ? indicator.nameZh || indicator.nameEn || indicator.seriesId
                                : indicator.nameEn || indicator.nameZh || indicator.seriesId}
                            </td>
                            <td className="px-2 py-2 font-mono text-secondary-text">
                              {formatMacroNumber(indicator.value, indicator.unit)}
                            </td>
                            <td className="px-2 py-2 font-mono text-secondary-text">
                              {formatMacroNumber(indicator.change, indicator.unit, true)}
                            </td>
                            <td className="px-2 py-2 text-secondary-text">{indicator.observationDate || '-'}</td>
                            <td className="px-2 py-2 text-secondary-text">{indicator.source || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {(() => {
                  const boardTypes = [{
                    key: 'sectors' as const,
                    title: marketReviewText.industryBoards,
                    rankings: activeMarketData.sectors,
                  }, {
                    key: 'concepts' as const,
                    title: marketReviewText.conceptBoards,
                    rankings: activeMarketData.concepts,
                  }].filter(({ rankings }) => hasRankingRows(rankings));
                  if (boardTypes.length === 0) {
                    return null;
                  }
                  const renderPanels = (
                    key: string,
                    title: string,
                    rankings: MarketReviewPayload['sectors'],
                  ) => (['top', 'bottom'] as const).map((side) => {
                    const rows = rankings?.[side] || [];
                    if (rows.length === 0) {
                      return null;
                    }
                    return (
                      <div key={`${key}-${side}`} className="rounded-lg border border-subtle p-3">
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <p className="label-uppercase">{title}</p>
                          <span className="text-xs text-secondary-text">
                            {side === 'top' ? marketReviewText.leading : marketReviewText.lagging}
                          </span>
                        </div>
                        <div className="space-y-1.5">
                          {rows.slice(0, 5).map((item, index) => (
                            <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 text-sm">
                              <span className="min-w-0 truncate text-foreground">{item.name}</span>
                              <span className="shrink-0 font-mono text-secondary-text">
                                {formatRankingChange(item.changePct)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  });
                  // 两类板块都存在时按 行业|概念 左右并列，节省纵向空间；只有一类时保留 领涨|领跌 横向布局。
                  if (boardTypes.length >= 2) {
                    return (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        {boardTypes.map(({ key, title, rankings }) => (
                          <div key={key} className="space-y-3">
                            {renderPanels(key, title, rankings)}
                          </div>
                        ))}
                      </div>
                    );
                  }
                  const { key, title, rankings } = boardTypes[0];
                  return (
                    <div key={key} className="grid grid-cols-1 gap-3 md:grid-cols-2">
                      {renderPanels(key, title, rankings)}
                    </div>
                  );
                })()}
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      {isLoading ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="flex h-64 flex-col items-center justify-center">
            <div className="home-spinner h-10 w-10 animate-spin border-[3px]" />
            <p className="mt-4 text-sm text-secondary-text">{text.loadingReport}</p>
          </div>
        </Card>
      ) : error ? (
        <Card variant="bordered" padding="md" className="home-panel-card text-left">
          <div className="flex h-64 flex-col items-center justify-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-danger/10">
              <ShieldAlert className="h-6 w-6 text-danger" aria-hidden="true" />
            </div>
            <p className="text-sm text-danger">{error}</p>
          </div>
        </Card>
      ) : (
        <div data-testid="market-review-report" className="space-y-4">
          {effectiveSections.map(({ id, title, content: sectionContent, icon: Icon }) => (
            <Card key={id} variant="bordered" padding="md" className="home-panel-card text-left">
              <div className="mb-3 flex items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
                <h3 className="text-base font-semibold text-foreground">{title}</h3>
              </div>
              <ReportMarkdownBody
                content={sectionContent}
                className="market-review-markdown"
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};
