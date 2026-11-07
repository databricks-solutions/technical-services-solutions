import type { GenieAnswer } from './client';

export interface OneChatAnswer extends GenieAnswer {
  /** UC objects Genie One read. */
  assets: string[];
  /** True when Genie One searched workspace knowledge snippets, which other users may have written. */
  snippets: boolean;
}

/** Reads the Genie One (OneChat) SSE stream: the final text, the last SQL it ran, and what it read. */
export function parseOneChat(stream: string): OneChatAnswer {
  const text: string[] = [];
  const assets = new Set<string>();
  let sql: string | null = null;
  let snippets = false;
  for (const line of stream.split('\n')) {
    if (!line.startsWith('data:')) continue;
    let event: { type?: string; item?: Record<string, unknown> };
    try {
      event = JSON.parse(line.slice(5)) as typeof event;
    } catch {
      continue;
    }
    if (event.type !== 'response.output_item.added' || !event.item) continue;
    const item = event.item as {
      type?: string;
      name?: string;
      arguments?: string;
      content?: { type?: string; text?: string }[];
      metadata?: { ui_type?: string; identifier?: string };
    };
    if (item.type === 'message' && item.metadata?.ui_type !== 'THOUGHT')
      text.push(...(item.content ?? []).filter((c) => c.type === 'output_text' && c.text).map((c) => c.text ?? ''));
    if (item.type !== 'function_call') continue;
    if (item.name === 'search_knowledge_snippets') snippets = true;
    if (item.metadata?.identifier) assets.add(item.metadata.identifier);
    if (item.name === 'execute_sql_query') {
      try {
        const q = (JSON.parse(item.arguments ?? '{}') as { query?: unknown }).query;
        if (typeof q === 'string' && q.trim()) sql = q;
      } catch {
        // Arguments that are not JSON carry no SQL.
      }
    }
  }
  return { text: text.join('\n\n'), sql, assets: [...assets].slice(0, 50), snippets };
}

/** True when the SQL names the view, quoted or not. */
export function readsView(sql: string, view: string) {
  const flat = (s: string) => s.toLowerCase().replace(/[`"]/g, '');
  return flat(sql).includes(flat(view));
}
