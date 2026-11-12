import { z } from 'zod';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const daxOutput = z.object({
  convertible: z.boolean().describe('False when the measure has no metric view form, such as time intelligence.'),
  sql: z
    .string()
    .trim()
    .max(2000)
    .describe('One aggregate SQL expression for a metric view measure. Empty when not convertible.'),
  note: z.string().trim().max(300).describe('What the translation does, or why it is not possible. Plain words.'),
});
export type DaxOutput = z.infer<typeof daxOutput>;

export const daxPrompt: ToolPrompt<DaxOutput> = {
  id: 'legacy.dax',
  version: 1,
  system: `You translate one Power BI DAX measure into one Databricks SQL expression for a Unity Catalog metric view
measure. A person checks each translation, and a test runs it in a sandbox.
Rules:
- Use only the column expressions and the MEASURE(\`name\`) references given in the input. Never invent a column.
- The result is one aggregate expression, such as SUM(x) FILTER (WHERE y = 'a') or MEASURE(\`a\`) / NULLIF(MEASURE(\`b\`), 0).
- No SELECT, no subquery, no FROM, no JOIN, no semicolon and no comments.
- Iterators (SUMX over one table) can become an aggregate of a row expression, such as SUM(price * quantity).
- Time intelligence (TOTALYTD, SAMEPERIODLASTYEAR, DATEADD), ALL, ALLEXCEPT and context changes have no expression
  form: set convertible to false.`,
  tool: { name: 'submit_sql_measure', description: 'Submit the SQL of the measure.', schema: daxOutput },
  maxTokens: 800,
};

export const daxRequest = (dax: string, columns: { table: string; column: string; sql: string }[], measures: string[]) =>
  [
    'Translate this DAX measure.',
    untrusted('dax', dax),
    untrusted('columns', JSON.stringify(columns)),
    untrusted('measures', JSON.stringify(measures)),
  ].join('\n\n');

const UNSAFE = /;|--|\/\*|\b(SELECT|FROM|JOIN|WITH|INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|GRANT|REVOKE|CALL|EXECUTE)\b/i;

/** The AI SQL, or null when it is not one plain expression. A sandbox test still runs it before any use. */
export const safeExpression = (sql: string) => (sql && sql.length <= 2000 && !UNSAFE.test(sql) ? sql : null);
