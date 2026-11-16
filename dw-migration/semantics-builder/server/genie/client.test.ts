import { describe, expect, it } from 'vitest';
import { CHAT_COLUMNS, CHAT_ROWS, tableOf } from './client';

describe('tableOf', () => {
  it('keeps the first rows and columns and says when it cut', () => {
    const columns = Array.from({ length: CHAT_COLUMNS + 2 }, (_, i) => ({ name: `c${i}` }));
    const rows = Array.from({ length: CHAT_ROWS + 5 }, () => columns.map(() => '1'));
    const t = tableOf({ manifest: { schema: { columns } }, result: { data_array: rows } });
    expect(t?.columns).toHaveLength(CHAT_COLUMNS);
    expect(t?.rows).toHaveLength(CHAT_ROWS);
    expect(t?.rows[0]).toHaveLength(CHAT_COLUMNS);
    expect(t?.truncated).toBe(true);
  });

  it('returns null without columns, and a full small table as is', () => {
    expect(tableOf({})).toBeNull();
    expect(tableOf({ manifest: { schema: { columns: [{ name: 'n' }] } }, result: { data_array: [['3']] } })).toEqual({
      columns: ['n'],
      rows: [['3']],
      truncated: false,
    });
  });
});
