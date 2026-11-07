-- App state only: metadata about projects and sources, never business data rows.

CREATE TABLE gsb.project (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
  description text CHECK (length(description) <= 4000),
  target_catalog text,
  target_schema text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gsb.semantic_brief (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  content jsonb NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  confirmed_by text,
  confirmed_at timestamptz,
  UNIQUE (project_id, version)
);

CREATE TABLE gsb.source (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  full_name text NOT NULL,
  role text NOT NULL DEFAULT 'unknown' CHECK (role IN ('fact', 'dimension', 'unknown')),
  added_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, full_name)
);

CREATE TABLE gsb.readiness_report (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  source_id uuid NOT NULL REFERENCES gsb.source (id) ON DELETE CASCADE,
  score integer CHECK (score BETWEEN 0 AND 100),
  checks jsonb NOT NULL,
  assessment jsonb,
  model text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX readiness_report_source_idx ON gsb.readiness_report (source_id, created_at DESC);

CREATE TABLE gsb.recommendation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  readiness_report_id uuid REFERENCES gsb.readiness_report (id) ON DELETE SET NULL,
  kind text NOT NULL,
  title text NOT NULL,
  rationale text,
  statement text,
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'approved', 'applied', 'rejected', 'failed')),
  decided_by text,
  decided_at timestamptz,
  applied_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recommendation_project_idx ON gsb.recommendation (project_id, status);

-- No foreign key: audit rows must outlive the project they describe.
CREATE TABLE gsb.audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,
  action text NOT NULL,
  project_id uuid,
  target text,
  statement text,
  outcome text NOT NULL CHECK (outcome IN ('requested', 'approved', 'rejected', 'succeeded', 'failed')),
  detail jsonb
);
CREATE INDEX audit_log_project_idx ON gsb.audit_log (project_id, at DESC);

-- Append-only, also for the owning app role.
CREATE FUNCTION gsb.audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'gsb.audit_log is append-only';
END;
$$;
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON gsb.audit_log
  FOR EACH ROW EXECUTE FUNCTION gsb.audit_log_immutable();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON gsb.audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION gsb.audit_log_immutable();
