import { Typography } from '@databricks/design-system';
import type { ReactNode } from 'react';

/** Minimal, safe Markdown: ## headings, - bullets, **bold**, `code`, paragraphs. Builds React
 *  elements only (never HTML strings), so model output cannot inject markup. */
type Code = (text: string) => ReactNode | null;

function inline(text: string, code?: Code): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : part.startsWith('`') && part.endsWith('`') ? (
      <span key={i}>{code?.(part.slice(1, -1)) ?? <code>{part.slice(1, -1)}</code>}</span>
    ) : (
      part
    ),
  );
}

/** `code` can turn a code span into a link, for example to an object named in the answer. */
export function Markdown({ text, code }: { text: string; code?: Code }) {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`l${out.length}`}>{list.map((l, i) => <li key={i}>{inline(l, code)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (/^\s*[-*]\s+/.test(line)) {
      list.push(line.replace(/^\s*[-*]\s+/, ''));
      continue;
    }
    flush();
    if (/^#{1,6}\s/.test(line)) out.push(<Typography.Title key={out.length} level={4}>{inline(line.replace(/^#+\s/, ''), code)}</Typography.Title>);
    else if (line.trim()) out.push(<Typography.Paragraph key={out.length}>{inline(line, code)}</Typography.Paragraph>);
  }
  flush();
  return <div className="lbl-md">{out}</div>;
}
