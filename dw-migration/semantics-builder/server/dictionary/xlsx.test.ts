import { describe, expect, it } from 'vitest';
import writeExcelFile from 'write-excel-file/node';
import { DICTIONARY_EXAMPLES, DICTIONARY_SECTIONS, columnsFor } from '../../shared/dictionary';
import { parseFile } from '../api/dictionary';

describe('parseFile', () => {
  it('reads the Excel template back, skipping the Read me sheet', async () => {
    const sheets = [
      {
        data: [
          ['column', 'meaning'],
          ['name', 'Business name'],
        ],
        sheet: 'Read me',
      },
      ...DICTIONARY_SECTIONS.map((s) => {
        const cols = columnsFor(s.kind);
        return {
          data: [cols.map((c) => c.header), ...DICTIONARY_EXAMPLES[s.kind].map((r) => cols.map((c) => r[c.key] ?? ''))],
          sheet: s.title,
        };
      }),
    ];
    const buffer = await writeExcelFile(sheets).toBuffer();
    const { entries, problems } = await parseFile('dictionary.xlsx', buffer);
    expect(problems).toEqual([]);
    expect(entries.map((e) => `${e.kind}:${e.name}:${e.status}`)).toEqual([
      'metric:Net Revenue:certified',
      'metric:Average Order Value:approved',
      'dimension:Customer Region:approved',
      'term:Order:approved',
    ]);
    expect(entries[0].synonyms).toEqual(['net sales', 'revenue']);
  });

  it('refuses a file that is not a workbook, and files over the limit', async () => {
    await expect(parseFile('x.xlsx', Buffer.from('name,definition'))).rejects.toThrow(/not an Excel workbook/);
    await expect(parseFile('x.csv', Buffer.alloc(800 * 1024))).rejects.toThrow(/larger than/);
  });

  it('reads CSV with a kind column', async () => {
    const { entries } = await parseFile('d.csv', Buffer.from('kind,name,definition\ndimension,Region,Where it is\n'));
    expect(entries).toMatchObject([{ kind: 'dimension', name: 'Region' }]);
  });
});
