import { describe, expect, it } from 'vitest';
import { queryParts, testFromAnswer } from './genie';
import type { ChatAnswer } from './genie';

const answer = (a: Partial<ChatAnswer>): ChatAnswer => ({
  conversationId: 'c1',
  text: '',
  sql: 'SELECT MEASURE(revenue) FROM v',
  fields: { measures: ['revenue'], dimensions: [] },
  table: { columns: ['revenue'], rows: [['1234.5']], truncated: false },
  read: null,
  suggested: [],
  ...a,
});

describe('testFromAnswer', () => {
  it('makes an expected value test from one measure and one number', () => {
    expect(testFromAnswer(' Total revenue? ', answer({}))).toEqual({
      name: 'Total revenue?',
      measures: ['revenue'],
      dimensions: [],
      expect: { value: 1234.5, tolerancePct: 0.5, filters: [] },
    });
  });

  it('keeps simple WHERE filters on dimensions as test filters', () => {
    const sql =
      "SELECT MEASURE(`Net Revenue`) FROM v WHERE `Customer Region` ILIKE '%ASIA%' AND year = 'it\\'s' GROUP BY ALL";
    expect(
      testFromAnswer('q', answer({ sql, fields: { measures: ['revenue'], dimensions: ['Customer Region', 'year'] } }))
        ?.expect?.filters
    ).toEqual([
      { dimension: 'Customer Region', value: 'ASIA' },
      { dimension: 'year', value: "it's" },
    ]);
  });

  it('makes a plain test when there is a group, another filter or no single number', () => {
    const plain = { name: 'q', measures: ['revenue'], dimensions: [] };
    expect(testFromAnswer('q', answer({ sql: 'SELECT MEASURE(revenue) FROM v WHERE year = 2024' }))).toEqual(plain);
    expect(testFromAnswer('q', answer({ sql: "SELECT MEASURE(revenue) FROM v WHERE a = 'x' OR a = 'y'" }))).toEqual(
      plain
    );
    expect(testFromAnswer('q', answer({ table: null }))).toEqual(plain);
    expect(testFromAnswer('q', answer({ table: { columns: ['revenue'], rows: [['n/a']], truncated: false } }))).toEqual(
      plain
    );
    expect(
      testFromAnswer(
        'q',
        answer({
          sql: 'SELECT region, MEASURE(revenue) FROM v',
          fields: { measures: ['revenue'], dimensions: ['region'] },
        })
      )
    ).toEqual({
      ...plain,
      dimensions: ['region'],
    });
  });

  it('makes no test when the SQL uses no measure', () => {
    expect(testFromAnswer('q', answer({ fields: { measures: [], dimensions: ['region'] } }))).toBeNull();
  });
});

describe('queryParts', () => {
  it('finds the group in the SELECT list and ignores IS NOT NULL', () => {
    const sql =
      'SELECT `Customer Region`, MEASURE(`Net Revenue`) FROM v WHERE `Customer Region` IS NOT NULL GROUP BY ALL';
    expect(queryParts(sql, ['Customer Region', 'Order Year'])).toEqual({ group: ['Customer Region'], filters: [] });
  });

  it('gives up on a subquery or a filter on a column that is not a dimension', () => {
    expect(queryParts('SELECT x FROM (SELECT 1 x)', ['x'])).toBeNull();
    expect(queryParts("SELECT MEASURE(m) FROM v WHERE other = 'a'", ['x'])).toBeNull();
  });
});
