import { describe, expect, it } from 'vitest';

import { toCamelCase } from '../utils';
import type { MarketReviewPayload } from '../../types/analysis';

describe('toCamelCase', () => {
  it('preserves unavailable and proxy index metadata from the market-review API', () => {
    const payload = toCamelCase<MarketReviewPayload>({
      version: 1,
      kind: 'market_review',
      region: 'us',
      language: 'zh',
      title: '美股大盘复盘',
      indices: [
        {
          code: 'NDX100',
          name: '纳斯达克100指数',
          data_unavailable: true,
          proxy: false,
          source: 'unavailable',
        },
      ],
      breadth: {
        market_stats_source: 'moomoo',
        market_stats_sample_size: 8000,
      },
    });

    expect(payload.indices?.[0]).toMatchObject({
      dataUnavailable: true,
      proxy: false,
      source: 'unavailable',
    });
    expect(payload.breadth?.marketStatsSource).toBe('moomoo');
    expect(payload.breadth?.marketStatsSampleSize).toBe(8000);
  });
});
