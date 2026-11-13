-- Monthly limit on app-run warehouse time (stress tests and materialization tries) per sub-project.
ALTER TABLE gsb.project ADD COLUMN stress_budget_ms bigint CHECK (stress_budget_ms > 0);
