export class StatementRejected extends Error {
  constructor(reason: string) {
    super(`Statement rejected: ${reason}`);
    this.name = 'StatementRejected';
  }
}

export type StatementKind = 'read' | 'ddl';

export interface CheckedStatement {
  kind: StatementKind;
  statement: string;
}

/**
 * Replaces the contents of strings, quoted identifiers and $$ blocks with 'x' (same length),
 * so the patterns below only see SQL structure. Comments are rejected so nothing hides in them.
 */
function mask(sql: string): string {
  let out = '';
  let i = 0;
  while (i < sql.length) {
    const c = sql[i];
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1;
      while (j < sql.length && sql[j] !== c) j += c !== '`' && sql[j] === '\\' ? 2 : 1;
      if (j >= sql.length) throw new StatementRejected('unterminated quoted text');
      out += c + 'x'.repeat(j - i - 1) + c;
      i = j + 1;
    } else if (c === '$' && sql[i + 1] === '$') {
      const end = sql.indexOf('$$', i + 2);
      if (end < 0) throw new StatementRejected('unterminated $$ block');
      out += '$$' + 'x'.repeat(end - i - 2) + '$$';
      i = end + 2;
    } else if ((c === '-' && sql[i + 1] === '-') || (c === '/' && sql[i + 1] === '*')) {
      throw new StatementRejected('comments are not allowed');
    } else {
      out += c;
      i++;
    }
  }
  return out;
}

const ID = '(?:[A-Za-z_][A-Za-z0-9_]*|`x+`)';
const name = (maxParts: number) => `${ID}(?:\\.${ID}){0,${maxParts - 1}}`;
const OBJ = name(3);
const COLUMN = name(4);
const STR = `(?:'x*'|"x*")+`;
const list = (item: string) => `\\(\\s*${item}(?:\\s*,\\s*${item})*\\s*\\)`;
const TAG_VALUE = `(?:${ID}|${STR})`;
const SECURABLE = '(?:CATALOG|SCHEMA|TABLE|VIEW)';
const TAG_SECURABLE = '(?:CATALOG|SCHEMA|TABLE|VIEW|COLUMN)';
const KEY_OPTIONS = '(?:\\s+(?:RELY|NOT\\s+ENFORCED))*';
// Grants are limited to read access on published objects.
const PRIVILEGE = '(?:SELECT|BROWSE|USE\\s+CATALOG|USE\\s+SCHEMA)';

const DDL_PATTERNS = [
  `COMMENT\\s+ON\\s+${SECURABLE}\\s+${OBJ}\\s+IS\\s+(?:${STR}|NULL)`,
  `COMMENT\\s+ON\\s+COLUMN\\s+${COLUMN}\\s+IS\\s+(?:${STR}|NULL)`,
  `ALTER\\s+TABLE\\s+${OBJ}\\s+ALTER\\s+COLUMN\\s+${ID}\\s+(?:COMMENT\\s+${STR}|SET\\s+NOT\\s+NULL)`,
  `ALTER\\s+TABLE\\s+${OBJ}\\s+ADD\\s+CONSTRAINT\\s+${ID}\\s+PRIMARY\\s+KEY\\s*${list(ID)}${KEY_OPTIONS}`,
  `ALTER\\s+TABLE\\s+${OBJ}\\s+ADD\\s+CONSTRAINT\\s+${ID}\\s+FOREIGN\\s+KEY\\s*${list(ID)}\\s+REFERENCES\\s+${OBJ}\\s*${list(ID)}${KEY_OPTIONS}`,
  `ALTER\\s+(?:TABLE|VIEW)\\s+${OBJ}(?:\\s+ALTER\\s+COLUMN\\s+${ID})?\\s+(?:SET\\s+TAGS\\s*${list(`${STR}\\s*=\\s*${STR}`)}|UNSET\\s+TAGS\\s*${list(STR)})`,
  `SET\\s+TAG\\s+ON\\s+${TAG_SECURABLE}\\s+${COLUMN}\\s+${TAG_VALUE}(?:\\s*=\\s*${TAG_VALUE})?`,
  `UNSET\\s+TAG\\s+ON\\s+${TAG_SECURABLE}\\s+${COLUMN}\\s+${TAG_VALUE}`,
  `CREATE\\s+(?:OR\\s+REPLACE\\s+)?VIEW\\s+${OBJ}\\s+WITH\\s+METRICS\\s+LANGUAGE\\s+YAML(?:\\s+COMMENT\\s+${STR})?\\s+AS\\s+\\$\\$x*\\$\\$`,
  `GRANT\\s+${PRIVILEGE}(?:\\s*,\\s*${PRIVILEGE})*\\s+ON\\s+${SECURABLE}\\s+${OBJ}\\s+TO\\s+\`x+\``,
].map((p) => new RegExp(`^${p}$`, 'i'));

const MAX_LENGTH = 200_000;

const READ_HEAD = /^(?:EXPLAIN(?:\s+(?:EXTENDED|FORMATTED|COST))?\s+)?(?:SELECT|WITH)\b/i;
const DESCRIBE = new RegExp(`^DESCRIBE\\s+(?:TABLE\\s+)?(?:EXTENDED\\s+)?${OBJ}$`, 'i');
const WRITE_KEYWORD =
  /\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|COPY|OPTIMIZE|VACUUM|REFRESH)\b/i;

/** Accepts one allowlisted statement or throws StatementRejected. DDL still needs human approval. */
export function checkStatement(sql: string): CheckedStatement {
  if (sql.length > MAX_LENGTH) throw new StatementRejected('statement is too long');
  const masked = mask(sql);
  const start = masked.search(/\S/);
  let end = masked.length;
  while (end > 0 && /[\s;]/.test(masked[end - 1])) end--;
  if (start < 0 || start >= end) throw new StatementRejected('empty statement');
  const core = masked.slice(start, end);
  if (core.includes(';')) throw new StatementRejected('only one statement is allowed');

  const statement = sql.slice(start, end);
  if (READ_HEAD.test(core)) {
    if (WRITE_KEYWORD.test(core)) throw new StatementRejected('read statements cannot write');
    return { kind: 'read', statement };
  }
  if (DESCRIBE.test(core)) return { kind: 'read', statement };
  if (DDL_PATTERNS.some((p) => p.test(core))) return { kind: 'ddl', statement };
  throw new StatementRejected('statement type is not on the allowlist');
}
