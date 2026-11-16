CREATE OR REPLACE PACKAGE BODY fin.pkg_finance AS

  PROCEDURE load_gl IS
  BEGIN
    INSERT /*+ APPEND */ INTO stg.gl_entries (entry_id, account_id, amount, period_id)
    SELECT e.entry_id, e.account_id, e.debit - e.credit, p.period_id
    FROM raw.journal_entries e
    JOIN raw.periods p ON e.posting_date BETWEEN p.start_date AND p.end_date
    WHERE e.status = 'POSTED';

    MERGE INTO dw.fact_gl t
    USING (SELECT g.account_id, g.period_id, SUM(g.amount) AS amount
           FROM stg.gl_entries g GROUP BY g.account_id, g.period_id) s
    ON (t.account_id = s.account_id AND t.period_id = s.period_id)
    WHEN MATCHED THEN UPDATE SET t.amount = s.amount
    WHEN NOT MATCHED THEN INSERT (account_id, period_id, amount) VALUES (s.account_id, s.period_id, s.amount);
    COMMIT;
  END load_gl;

  PROCEDURE build_balances IS
    CURSOR c_accounts IS SELECT account_id FROM dw.dim_account WHERE active_flag = 'Y';
  BEGIN
    FOR r IN c_accounts LOOP
      INSERT INTO mart.account_balance (account_id, balance)
      SELECT f.account_id, SUM(f.amount) FROM dw.fact_gl f WHERE f.account_id = r.account_id GROUP BY f.account_id;
    END LOOP;
    EXECUTE IMMEDIATE 'TRUNCATE TABLE stg.gl_entries';
  END build_balances;

END pkg_finance;
/
