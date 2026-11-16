/** The connection check for BI tools: the SQL shape that Power BI Native query and Tableau Custom SQL send. */
export interface BiCheck {
  target: string | null;
  version: number | null;
  /** The query to paste into the BI tool, and the one the check ran. */
  sql: string | null;
  dimension: string | null;
  measure: string | null;
  /** Set after a run: pass or fail, the number of rows, never the values. */
  result: { status: 'passed' | 'failed'; rows: number; detail: string } | null;
}

/** Tableau live connections can query a metric view like a table in BI compatibility mode (SQL warehouse). */
export const BI_COMPATIBILITY_SQL = 'SET metric_view_bi_compatibility_mode = true;';
