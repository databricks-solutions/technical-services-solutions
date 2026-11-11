import { describe, expect, it } from 'vitest';
import { testFromAnswer } from './genie';
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

  it('makes a plain test when there is a group, a filter or no single number', () => {
    const plain = { name: 'q', measures: ['revenue'], dimensions: [] };
    expect(testFromAnswer('q', answer({ sql: 'SELECT MEASURE(revenue) FROM v WHERE year = 2024' }))).toEqual(plain);
    expect(testFromAnswer('q', answer({ table: null }))).toEqual(plain);
    expect(testFromAnswer('q', answer({ table: { columns: ['revenue'], rows: [['n/a']], truncated: false } }))).toEqual(
      plain
    );
    expect(testFromAnswer('q', answer({ fields: { measures: ['revenue'], dimensions: ['region'] } }))).toEqual({
      ...plain,
      dimensions: ['region'],
    });
  });

  it('makes no test when the SQL uses no measure', () => {
    expect(testFromAnswer('q', answer({ fields: { measures: [], dimensions: ['region'] } }))).toBeNull();
  });
});
