import { describe, expect, it } from 'vitest';
import { checkStatement, StatementRejected } from './allowlist';

const MV = `CREATE OR REPLACE VIEW sandbox.gsb.orders_mv
WITH METRICS
LANGUAGE YAML
AS $$
version: 1.1
source: samples.tpch.orders
comment: "a; b -- not a comment"
dimensions:
  - name: Order Date
    expr: o_orderdate
measures:
  - name: Revenue
    expr: SUM(o_totalprice)
$$`;

describe('checkStatement accepts the allowlist', () => {
  it.each([
    ['read', 'SELECT * FROM samples.tpch.orders LIMIT 10'],
    ['read', 'select count(*) from `my-catalog`.tpch.orders;'],
    ['read', 'WITH t AS (SELECT 1 AS x) SELECT x FROM t'],
    ['read', 'EXPLAIN EXTENDED SELECT MEASURE(Revenue) FROM sandbox.gsb.orders_mv'],
    ['read', "SELECT 'DROP TABLE x; --' AS s"],
    ['read', 'DESCRIBE TABLE EXTENDED samples.tpch.orders'],
    ['read', 'describe `my-catalog`.tpch.orders'],
    ['read', 'DESCRIBE CATALOG EXTENDED `my-catalog`'],
    ['read', 'SHOW GRANTS ON VIEW `main`.`sales`.`orders_mv`'],
    ['ddl', "COMMENT ON TABLE `sandbox`.`gsb`.`orders` IS 'It\\'s a \\\\ test'"],
    ['ddl', "COMMENT ON TABLE samples.tpch.orders IS 'Customer orders'"],
    ['ddl', "COMMENT ON COLUMN sandbox.gsb.orders.o_orderkey IS 'it''s the key'"],
    ['ddl', 'COMMENT ON TABLE sandbox.gsb.orders IS NULL'],
    ['ddl', "ALTER TABLE sandbox.gsb.orders ALTER COLUMN o_orderkey COMMENT 'Order key'"],
    ['ddl', 'ALTER TABLE sandbox.gsb.orders ALTER COLUMN o_orderkey SET NOT NULL'],
    ['ddl', 'ALTER TABLE sandbox.gsb.orders ADD CONSTRAINT orders_pk PRIMARY KEY (o_orderkey)'],
    [
      'ddl',
      'ALTER TABLE sandbox.gsb.orders ADD CONSTRAINT orders_cust_fk FOREIGN KEY (o_custkey) REFERENCES sandbox.gsb.customer (c_custkey) NOT ENFORCED',
    ],
    ['ddl', "ALTER TABLE sandbox.gsb.orders SET TAGS ('domain' = 'sales', 'pii' = 'false')"],
    ['ddl', "ALTER TABLE sandbox.gsb.orders ALTER COLUMN o_comment SET TAGS ('pii' = 'true')"],
    ['ddl', "ALTER VIEW sandbox.gsb.orders_mv UNSET TAGS ('domain')"],
    ['ddl', 'SET TAG ON TABLE sandbox.gsb.orders domain = sales'],
    ['ddl', 'UNSET TAG ON COLUMN sandbox.gsb.orders.o_comment pii'],
    ['ddl', MV],
    ['ddl', MV.replace('OR REPLACE ', '')],
    ['ddl', 'GRANT SELECT ON TABLE sandbox.gsb.orders_mv TO `analysts`'],
    ['ddl', 'GRANT USE CATALOG ON CATALOG sandbox TO `user@example.com`'],
    ['ddl', 'GRANT USE SCHEMA, SELECT ON SCHEMA sandbox.gsb TO `analysts`'],
    ['ddl', 'REVOKE SELECT ON VIEW main.sales.orders_mv FROM `analysts`'],
    ['ddl', 'ALTER VIEW `main`.`sales`.`orders_mv` OWNER TO `data team`'],
    ['ddl', 'DROP VIEW IF EXISTS `sandbox`.`gsb`.`sales__gsb_47d9362a`'],
    ['ddl', 'DROP VIEW sandbox.gsb.sales__gsb_47d9362a'],
  ])('%s: %s', (kind, sql) => {
    expect(checkStatement(sql).kind).toBe(kind);
  });

  it('returns the trimmed statement without trailing semicolons', () => {
    expect(checkStatement('  SELECT 1 ;; \n').statement).toBe('SELECT 1');
  });
});

describe('checkStatement reads information_schema', () => {
  it('accepts the metric view list of the library', () => {
    expect(
      checkStatement(
        `SELECT table_catalog, table_schema, table_name, table_owner, CAST(last_altered AS STRING), comment
         FROM system.information_schema.tables WHERE table_type = 'METRIC_VIEW'
         ORDER BY last_altered DESC LIMIT 1000`
      ).kind
    ).toBe('read');
  });
});

describe('checkStatement rejects everything else', () => {
  it.each([
    ['empty', '   '],
    ['too long', `SELECT '${'x'.repeat(200_001)}'`],
    ['only semicolons', ' ;; '],
    ['multi-statement', 'SELECT 1; DROP TABLE x'],
    ['multi-statement after comment', "COMMENT ON TABLE a.b.c IS 'x'; DROP TABLE a.b.c"],
    ['line comment', 'SELECT 1 -- hide'],
    ['block comment', 'SELECT /* x */ 1'],
    ['unterminated string', "COMMENT ON TABLE a.b.c IS 'oops"],
    ['unterminated dollar block', 'CREATE VIEW a.b.c WITH METRICS LANGUAGE YAML AS $$ version: 1.1'],
    ['drop', 'DROP TABLE sandbox.gsb.orders'],
    ['drop non-sandbox view', 'DROP VIEW sandbox.gsb.orders_mv'],
    ['drop sandbox-like table', 'DROP TABLE sandbox.gsb.sales__gsb_47d9362a'],
    ['drop view with suffix inside', 'DROP VIEW `a`.`b`.`x__gsb_47d9362a_real`'],
    ['drop view with short suffix', 'DROP VIEW a.b.x__gsb_47d9'],
    ['insert', 'INSERT INTO sandbox.gsb.orders VALUES (1)'],
    ['cte write', 'WITH t AS (SELECT 1) INSERT INTO x SELECT * FROM t'],
    ['delete in select', 'SELECT * FROM (DELETE FROM x)'],
    ['plain view', 'CREATE VIEW sandbox.gsb.v AS SELECT 1'],
    ['metric view not yaml body', 'CREATE VIEW a.b.c WITH METRICS LANGUAGE YAML AS SELECT 1'],
    ['revoke modify', 'REVOKE MODIFY ON TABLE a.b.c FROM `x`'],
    ['revoke all', 'REVOKE ALL PRIVILEGES ON VIEW a.b.c FROM `x`'],
    ['revoke unquoted principal', 'REVOKE SELECT ON VIEW a.b.c FROM users'],
    ['view owner unquoted', 'ALTER VIEW a.b.c OWNER TO users'],
    ['schema owner', 'ALTER SCHEMA a.b OWNER TO `x`'],
    ['show grants on schema', 'SHOW GRANTS ON SCHEMA a.b'],
    ['grant all', 'GRANT ALL PRIVILEGES ON CATALOG sandbox TO `x`'],
    ['grant modify', 'GRANT MODIFY ON TABLE a.b.c TO `x`'],
    ['grant manage', 'GRANT MANAGE ON SCHEMA a.b TO `x`'],
    ['grant unquoted principal', 'GRANT SELECT ON TABLE a.b.c TO users'],
    ['alter drop column', 'ALTER TABLE a.b.c DROP COLUMN x'],
    ['alter owner', 'ALTER TABLE a.b.c OWNER TO `x`'],
    ['alter set tblproperties', "ALTER TABLE a.b.c SET TBLPROPERTIES ('a'='b')"],
    ['check constraint', 'ALTER TABLE a.b.c ADD CONSTRAINT k CHECK (x > 0)'],
    ['bad identifier', "COMMENT ON TABLE a.b.c;x IS 'y'"],
    ['too many name parts', "COMMENT ON TABLE a.b.c.d IS 'y'"],
    ['optimize', 'OPTIMIZE a.b.c'],
    ['describe history', 'DESCRIBE HISTORY a.b.c'],
    ['describe catalog with schema', 'DESCRIBE CATALOG a.b'],
    ['copy into', "COPY INTO a.b.c FROM 's3://x'"],
  ])('%s', (_label, sql) => {
    expect(() => checkStatement(sql)).toThrow(StatementRejected);
  });
});
