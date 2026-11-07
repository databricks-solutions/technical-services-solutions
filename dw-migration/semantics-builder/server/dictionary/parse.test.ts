import { describe, expect, it } from 'vitest';
import { markdownTemplate } from '../../shared/dictionary';
import { entriesFromTable, parseCsv, parseMarkdown } from './parse';

describe('parseCsv', () => {
  it('reads quoted cells, commas and line breaks in quotes', () => {
    expect(parseCsv('name,definition\n"Net, Revenue","Value ""after"" discounts\nbefore tax"\n')).toEqual([
      ['name', 'definition'],
      ['Net, Revenue', 'Value "after" discounts\nbefore tax'],
    ]);
  });
});

describe('entriesFromTable', () => {
  it('maps headers by alias and keeps unknown columns as notes', () => {
    const { entries, problems } = entriesFromTable(
      [
        ['Metric Name', 'Description', 'Expression', 'AKA', 'Team'],
        ['Net Revenue', 'After discounts.', 'SUM(x)', 'net sales; revenue', 'Finance'],
      ],
      'metric'
    );
    expect(problems).toEqual([]);
    expect(entries[0]).toMatchObject({
      kind: 'metric',
      name: 'Net Revenue',
      definition: 'After discounts.',
      formula: 'SUM(x)',
      synonyms: ['net sales', 'revenue'],
      notes: { Team: 'Finance' },
      status: 'draft',
    });
  });

  it('reports missing fields, bad values and duplicates by row', () => {
    const { entries, problems } = entriesFromTable(
      [
        ['name', 'definition', 'aggregation', 'status'],
        ['A', '', 'sum', 'approved'],
        ['B', 'ok', 'total', 'done'],
        ['C', 'ok', '', ''],
        ['c', 'again', '', ''],
        ['', '', '', ''],
      ],
      'metric',
      'Metrics'
    );
    expect(entries.map((e) => e.name)).toEqual(['B', 'C']);
    expect(problems).toEqual([
      'Metrics row 2: definition is empty.',
      'Metrics row 3: aggregation "total" is not one of sum, count, count_distinct, avg, min, max, ratio, other. It was left out.',
      'Metrics row 3: status "done" is not one of draft, approved, certified. It was set to draft.',
      'Metrics row 5: "c" is already on row 4.',
    ]);
  });

  it('needs a name column', () => {
    expect(entriesFromTable([['title', 'text']], 'metric').problems[0]).toMatch(/no name column/);
  });
});

describe('parseMarkdown', () => {
  it('reads the template back, with the kind from each heading', () => {
    const { entries, problems } = parseMarkdown(markdownTemplate());
    expect(problems).toEqual([]);
    expect(entries.map((e) => `${e.kind}:${e.name}`)).toEqual([
      'metric:Net Revenue',
      'metric:Average Order Value',
      'dimension:Customer Region',
      'term:Order',
    ]);
    expect(entries[0].status).toBe('certified');
  });
});
