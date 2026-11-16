import type { FieldChanges } from './promote';

/** One line of a YAML diff: kept, only in the older version, or only in the newer one. */
export interface DiffLine {
  kind: 'same' | 'removed' | 'added';
  text: string;
}

/** Two versions of a design side by side: what the fields, the tests and the YAML lines changed. */
export interface VersionDiff {
  from: number;
  to: number;
  changes: FieldChanges | null;
  tests: { added: string[]; removed: string[] };
  lines: DiffLine[];
}

const MAX_LINES = 2000;

/** A line diff by longest common subsequence. Designs are small, so the quadratic table is fine. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split('\n').slice(0, MAX_LINES);
  const b = after.split('\n').slice(0, MAX_LINES);
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ kind: 'removed', text: a[i++] });
    else out.push({ kind: 'added', text: b[j++] });
  }
  while (i < a.length) out.push({ kind: 'removed', text: a[i++] });
  while (j < b.length) out.push({ kind: 'added', text: b[j++] });
  return out;
}
