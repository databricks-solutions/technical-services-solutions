import { FormUI, Input } from '@databricks/design-system';

const COMMENT = /^(COMMENT ON (?:TABLE|COLUMN) (.+) IS )'((?:[^'\\]|\\.)*)'$/s;
const unquote = (s: string) => s.replace(/\\(.)/g, '$1');
// Preview only. The server rebuilds the statement from the text and is the authority.
const quote = (s: string) => `'${s.trim().replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;

/** Comment statements as editable text: the target, then the proposed comment. */
export const commentsOf = (statements: string[]) =>
  statements.map((s) => {
    const m = COMMENT.exec(s);
    return m ? { prefix: m[1], target: m[2].replace(/`/g, ''), text: unquote(m[3]) } : null;
  });

/** The statements with the edited text, for the preview. */
export const previewOf = (statements: string[], edits: (string | null)[]) =>
  statements.map((s, i) => {
    const c = commentsOf([s])[0];
    const e = edits[i];
    return c && e != null ? `${c.prefix}${quote(e)}` : s;
  });

export function CommentEdits({
  statements,
  edits,
  onChange,
}: {
  statements: string[];
  edits: (string | null)[];
  onChange: (edits: (string | null)[]) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {commentsOf(statements).map((c, i) =>
        c ? (
          <div key={c.target}>
            <FormUI.Label htmlFor={`ce-${i}`}>{c.target}</FormUI.Label>
            <Input.TextArea
              componentId="gsb.sources.comment_edit"
              id={`ce-${i}`}
              autoSize={{ minRows: 1, maxRows: 4 }}
              maxLength={1000}
              value={edits[i] ?? c.text}
              onChange={(e) => onChange(statements.map((_, j) => (j === i ? e.target.value : (edits[j] ?? null))))}
            />
          </div>
        ) : null
      )}
    </div>
  );
}
