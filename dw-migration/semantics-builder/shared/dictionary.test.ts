import { describe, expect, it } from 'vitest';
import { DICTIONARY_COLUMNS, columnsFor, markdownTemplate } from './dictionary';

describe('dictionary template', () => {
  it('requires only name and definition', () => {
    expect(DICTIONARY_COLUMNS.filter((c) => c.required).map((c) => c.key)).toEqual(['name', 'definition']);
  });

  it('gives each section only the columns that apply', () => {
    expect(columnsFor('term').map((c) => c.key)).toEqual(['name', 'definition', 'synonyms', 'owner', 'status']);
    expect(columnsFor('metric').map((c) => c.key)).toContain('aggregation');
    expect(columnsFor('dimension').map((c) => c.key)).not.toContain('aggregation');
  });

  it('writes one pipe table per section with the examples', () => {
    const md = markdownTemplate();
    expect(md).toContain('## Metrics');
    expect(md).toContain('## Dimensions');
    expect(md).toContain('## Glossary');
    expect(md).toContain('| Net Revenue | Net revenue |');
    expect(md).toContain('SUM(l_extendedprice * (1 - l_discount))');
  });
});
