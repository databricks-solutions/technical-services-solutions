import { describe, expect, it } from 'vitest';
import { parseOneChat, readsView } from './onechat';

const ev = (item: object, type = 'response.output_item.added') => `data:${JSON.stringify({ type, item })}\n\n`;

describe('parseOneChat', () => {
  it('keeps the final text, the last SQL and what Genie One read', () => {
    const stream = [
      `data:${JSON.stringify({ type: 'response.created' })}\n\n`,
      ev({
        type: 'message',
        content: [{ type: 'output_text', text: 'I will look.' }],
        metadata: { ui_type: 'THOUGHT' },
      }),
      ev({
        type: 'function_call',
        name: 'get_asset_info',
        arguments: '{}',
        metadata: { identifier: 'c.s.v' },
      }),
      ev({ type: 'function_call', name: 'search_knowledge_snippets', arguments: '{"query":"revenue"}', metadata: {} }),
      ev({ type: 'function_call', name: 'execute_sql_query', arguments: '{"query":"SELECT 1"}' }),
      ev({
        type: 'function_call',
        name: 'execute_sql_query',
        arguments: JSON.stringify({ query: 'SELECT MEASURE(`Net Revenue`) FROM c.s.v' }),
      }),
      'data:{not json\n\n',
      ev({ type: 'message', content: [{ type: 'output_text', text: 'Net revenue is 10.' }], metadata: {} }),
    ].join('');
    expect(parseOneChat(stream)).toEqual({
      text: 'Net revenue is 10.',
      sql: 'SELECT MEASURE(`Net Revenue`) FROM c.s.v',
      assets: ['c.s.v'],
      snippets: true,
    });
  });
  it('returns no SQL when Genie One ran none', () => {
    expect(parseOneChat('')).toEqual({ text: '', sql: null, assets: [], snippets: false });
  });
});

describe('readsView', () => {
  it('matches quoted and unquoted names', () => {
    expect(readsView('SELECT * FROM `c`.`s`.`v`', 'c.s.v')).toBe(true);
    expect(readsView('SELECT * FROM C.S.V', 'c.s.v')).toBe(true);
    expect(readsView('SELECT * FROM c.s.other', 'c.s.v')).toBe(false);
  });
});
