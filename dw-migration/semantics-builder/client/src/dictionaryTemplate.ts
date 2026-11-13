import writeExcelFile from 'write-excel-file/browser';
import type { SheetData } from 'write-excel-file/browser';
import {
  DICTIONARY_COLUMNS,
  DICTIONARY_EXAMPLES,
  DICTIONARY_SECTIONS,
  columnsFor,
  markdownTemplate,
} from '../../shared/dictionary';

function download(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}

const bold = (value: string) => ({ value, fontWeight: 'bold' as const });

/** The Excel template: a Read me sheet, then one sheet per section with headers and example rows. */
export async function downloadExcelTemplate() {
  const readMe: SheetData = [
    [bold('Metric dictionary template')],
    ['Fill one row per entry on the Metrics, Dimensions and Glossary sheets. Keep the header row.'],
    ['Only name and definition are required. Extra columns are kept as notes.'],
    [],
    [bold('column'), bold('required'), bold('meaning')],
    ...DICTIONARY_COLUMNS.map((c) => [c.header, c.required ? 'yes' : 'no', c.help]),
  ];
  const sheets = [
    { data: readMe, sheet: 'Read me', columns: [{ width: 16 }, { width: 10 }, { width: 90 }] },
    ...DICTIONARY_SECTIONS.map((s) => {
      const cols = columnsFor(s.kind);
      const data: SheetData = [
        cols.map((c) => bold(c.header)),
        ...DICTIONARY_EXAMPLES[s.kind].map((r) => cols.map((c) => r[c.key] ?? '')),
      ];
      return {
        data,
        sheet: s.title,
        columns: cols.map((c) => ({ width: c.key === 'definition' || c.key === 'formula' ? 50 : 20 })),
      };
    }),
  ];
  download(await writeExcelFile(sheets).toBlob(), 'metric-dictionary-template.xlsx');
}

export function downloadMarkdownTemplate() {
  download(new Blob([markdownTemplate()], { type: 'text/markdown' }), 'metric-dictionary-template.md');
}
