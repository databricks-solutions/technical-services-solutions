import type { DesignOutput } from '../llm/prompts/designer';
import type { TableProfile } from '../readiness/profile';
import { inferLinks } from '../readiness/score';

const NUMERIC = /^(tinyint|smallint|int|integer|bigint|long|float|double|decimal|numeric)/i;
const TEMPORAL = /^(date|timestamp)/i;
const STRING = /^(string|varchar|char)/i;
const AMOUNT = /(price|amount|amt|cost|revenue|sales|qty|quantity|discount|tax|total|balance)/i;
const UNIT = /(unit_?price|rate|pct|percent|ratio)/i;
const KEYLIKE = /(_id|_sk|_key|key|id)$/i;

const short = (fullName: string) => fullName.split('.').pop()!.toLowerCase();
/** `o_totalprice` -> `Totalprice`, `totalPrice` -> `Total Price`, `sales_customers` -> `Sales Customers`. */
const title = (name: string) =>
  name
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/^[a-z]{1,3}_(?=.)/, '')
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
const column = (c: string) => (/^[A-Za-z_]\w*$/.test(c) ? c : `\`${c.replace(/`/g, '``')}\``);
const field = (name: string, expr: string, comment: string, explanation: string) => ({
  name,
  expr,
  comment,
  displayName: null,
  synonyms: [],
  format: null,
  explanation,
});

interface Edge {
  from: string;
  to: string;
  keys: { parentColumn: string; column: string }[];
}

/**
 * A starting design built from the source profiles alone, with no model call: the fact table,
 * its many-to-one joins, a row count, sums of amount columns, date dimensions and one name per join.
 */
export function templateDesign(profiles: TableProfile[], fact?: string): DesignOutput {
  const byName = new Map(profiles.map((p) => [p.fullName.toLowerCase(), p]));
  const edges: Edge[] = [
    ...profiles.flatMap((p) =>
      p.foreignKeys.map((fk) => ({
        from: p.fullName,
        to: fk.references,
        keys: fk.columns.map((c, i) => ({ parentColumn: c, column: fk.refColumns[i] ?? c })),
      }))
    ),
    ...inferLinks(profiles).map((l) => ({
      from: l.from,
      to: l.to,
      keys: [{ parentColumn: l.column, column: l.refColumn }],
    })),
  ].filter((e) => byName.has(e.to.toLowerCase()));

  const outgoing = (t: string) => edges.filter((e) => e.from.toLowerCase() === t.toLowerCase());
  const source =
    (fact ? byName.get(fact.toLowerCase()) : undefined) ??
    [...profiles].sort((a, b) => outgoing(b.fullName).length - outgoing(a.fullName).length)[0];

  const joins: DesignOutput['joins'] = [];
  const aliasOf = new Map<string, string | null>([[source.fullName.toLowerCase(), null]]);
  const queue = [source.fullName];
  while (queue.length && joins.length < 20) {
    const from = queue.shift()!;
    for (const e of outgoing(from)) {
      const key = e.to.toLowerCase();
      if (aliasOf.has(key)) continue;
      const target = byName.get(key)!;
      const name = `dim_${short(target.fullName).replace(/[^a-z0-9_]/g, '_')}`.slice(0, 63);
      aliasOf.set(key, name);
      joins.push({ name, source: target.fullName, parent: aliasOf.get(from.toLowerCase()) ?? null, keys: e.keys });
      queue.push(target.fullName);
    }
  }
  const chain = (alias: string): string => {
    const j = joins.find((x) => x.name === alias)!;
    return j.parent ? `${chain(j.parent)}.${alias}` : alias;
  };

  const measures: DesignOutput['measures'] = [
    {
      ...field('Row Count', 'COUNT(1)', `Number of rows in ${short(source.fullName)}.`, 'Counts the rows.'),
      additivity: 'additive',
    },
    ...source.columns
      .filter((c) => NUMERIC.test(c.type) && AMOUNT.test(c.name) && !KEYLIKE.test(c.name))
      .map((c) => {
        const t = title(c.name);
        // A unit price or a rate does not add up across rows; its average does mean something.
        return UNIT.test(c.name)
          ? {
              ...field(
                `Average ${t}`,
                `AVG(source.${column(c.name)})`,
                c.comment || `Average of ${c.name}.`,
                `The average ${c.name} across the rows.`
              ),
              additivity: 'non_additive' as const,
            }
          : {
              ...field(
                /^total\b/i.test(t) ? t : `Total ${t}`,
                `SUM(source.${column(c.name)})`,
                c.comment || `Sum of ${c.name}.`,
                `Adds up ${c.name} across the rows.`
              ),
              additivity: 'additive' as const,
            };
      }),
  ];

  const dates = source.columns.filter((c) => TEMPORAL.test(c.type));
  const dimensions: DesignOutput['dimensions'] = [
    ...dates.flatMap((c) => [
      field(title(c.name), `source.${column(c.name)}`, c.comment || `${c.name} of the row.`, `The value of ${c.name}.`),
      field(
        `${title(c.name)} Month`,
        `DATE_TRUNC('MONTH', source.${column(c.name)})`,
        `Month of ${c.name}.`,
        `${c.name} cut to the first day of its month.`
      ),
    ]),
    ...joins.flatMap((j) => {
      const c = byName.get(j.source.toLowerCase())!.columns.find((x) => STRING.test(x.type) && /name/i.test(x.name));
      if (!c) return [];
      const table = title(
        short(j.source)
          .replace(/^[a-z]+_(?=[a-z]{3,})/, '')
          .replace(/([^s])s$/, '$1')
      );
      const col = title(c.name);
      const name = col.includes(table) ? col : `${table} ${col}`;
      return [
        field(
          name,
          `${chain(j.name)}.${column(c.name)}`,
          c.comment || `${c.name} of ${short(j.source)}.`,
          `The ${c.name} of the joined ${short(j.source)} row.`
        ),
      ];
    }),
  ];
  if (!dimensions.length) {
    const c = source.columns.find((x) => STRING.test(x.type)) ?? source.columns[0];
    dimensions.push(
      field(title(c.name), `source.${column(c.name)}`, c.comment || `${c.name} of the row.`, `The value of ${c.name}.`)
    );
  }

  const month = dimensions.find((d) => d.name.endsWith(' Month'));
  const tests: DesignOutput['tests'] = [
    { name: 'Row count overall', dimensions: [], measures: ['Row Count'] },
    ...dimensions
      .filter((d) => d !== month && !dates.some((c) => title(c.name) === d.name))
      .slice(0, 2)
      .map((d) => ({ name: `Row count by ${d.name}`, dimensions: [d.name], measures: ['Row Count'] })),
    ...(month
      ? [
          {
            name: `Measures by ${month.name}`,
            dimensions: [month.name],
            measures: measures.slice(0, 4).map((m) => m.name),
          },
        ]
      : []),
  ].slice(0, 5);

  const base =
    short(source.fullName)
      .replace(/[^a-z0-9_]/g, '_')
      .replace(/^[^a-z]+/, '') || 'source';
  return {
    name: `${base}_metrics`.slice(0, 100),
    comment: `Metrics on ${source.fullName}.`,
    source: source.fullName,
    filter: null,
    joins,
    dimensions,
    measures,
    tests,
    summary: `Started from the template, with no model. The fact table is ${source.fullName} with ${joins.length} join(s), a row count, ${measures.length - 1} sum(s) and ${dimensions.length} dimension(s). Edit the YAML to fit the brief.`,
  };
}
