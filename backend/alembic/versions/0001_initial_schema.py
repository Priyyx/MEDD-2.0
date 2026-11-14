"""MEDD 2.0 initial schema: 10 logical schemas, hierarchy, staging, metadata, audit, analytics views.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-12
"""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["master_data", "equipment_inventory", "procurement", "financial", "maintenance",
           "lifecycle", "analytics", "staging", "metadata", "audit"]

DDL = r"""
-- ============================================================ MASTER DATA
CREATE TABLE master_data.division (
    id           smallserial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    map_key      text UNIQUE,                 -- key used by the SVG map (e.g. 'kokan')
    map_cx       numeric(8,1),
    map_cy       numeric(8,1),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE master_data.district (
    id           smallserial PRIMARY KEY,
    name         text NOT NULL UNIQUE,
    division_id  smallint NOT NULL REFERENCES master_data.division(id),
    svg_path     text NOT NULL,
    label_x      numeric(8,1),
    label_y      numeric(8,1),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_district_division ON master_data.district(division_id);

CREATE TABLE master_data.institute (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE,
    name_key         text NOT NULL UNIQUE,
    division_id      smallint NOT NULL REFERENCES master_data.division(id),
    bedded_capacity  integer CHECK (bedded_capacity IS NULL OR bedded_capacity >= 0),
    is_active        boolean NOT NULL DEFAULT true,
    source           text NOT NULL DEFAULT 'excel',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_institute_division ON master_data.institute(division_id);

CREATE TABLE master_data.department (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE,
    name_key         text NOT NULL UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE master_data.equipment (
    id               serial PRIMARY KEY,
    name             text NOT NULL,              -- display name (first approved spelling)
    name_key         text NOT NULL UNIQUE,       -- standardised key (see ingestion standardiser)
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_equipment_name_trgm ON master_data.equipment (lower(name));

CREATE TABLE master_data.sub_category (
    id               serial PRIMARY KEY,
    name             text NOT NULL UNIQUE,
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- Approved mapping rules: alias -> canonical entity (institutes, departments, equipment, divisions)
CREATE TABLE master_data.name_alias (
    id               serial PRIMARY KEY,
    entity_type      text NOT NULL CHECK (entity_type IN ('division','institute','department','equipment','sub_category')),
    alias_key        text NOT NULL,
    canonical_name   text NOT NULL,
    approved         boolean NOT NULL DEFAULT true,
    source           text NOT NULL DEFAULT 'manual',
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (entity_type, alias_key)
);

-- ============================================================ METADATA (ingestion bookkeeping)
CREATE TABLE metadata.ingestion_file (
    id               bigserial PRIMARY KEY,
    original_name    text NOT NULL,
    stored_path      text,
    sha256           char(64) NOT NULL,
    size_bytes       bigint NOT NULL,
    status           text NOT NULL CHECK (status IN ('RECEIVED','PROCESSING','SUCCESS','SUCCESS_WITH_WARNINGS','FAILED','DUPLICATE','ROLLED_BACK')),
    dataset_types    text[],
    sync_mode        text,
    rows_read        integer DEFAULT 0,
    rows_valid       integer DEFAULT 0,
    rows_rejected    integer DEFAULT 0,
    rows_inserted    integer DEFAULT 0,
    rows_updated     integer DEFAULT 0,
    rows_unchanged   integer DEFAULT 0,
    rows_deactivated integer DEFAULT 0,
    warnings         integer DEFAULT 0,
    errors           integer DEFAULT 0,
    error_message    text,
    report_path      text,
    triggered_by     text NOT NULL DEFAULT 'watcher',
    received_at      timestamptz NOT NULL DEFAULT now(),
    started_at       timestamptz,
    finished_at      timestamptz
);
CREATE INDEX ix_ingestion_file_sha ON metadata.ingestion_file(sha256);
CREATE INDEX ix_ingestion_file_status ON metadata.ingestion_file(status, received_at DESC);

CREATE TABLE metadata.ingestion_sheet (
    id               bigserial PRIMARY KEY,
    file_id          bigint NOT NULL REFERENCES metadata.ingestion_file(id) ON DELETE CASCADE,
    sheet_name       text NOT NULL,
    dataset_type     text NOT NULL,
    header_row       integer,
    column_map       jsonb NOT NULL DEFAULT '{}'::jsonb,
    unmapped_columns jsonb NOT NULL DEFAULT '[]'::jsonb,
    rows_read        integer NOT NULL DEFAULT 0
);

CREATE TABLE metadata.validation_issue (
    id               bigserial PRIMARY KEY,
    file_id          bigint NOT NULL REFERENCES metadata.ingestion_file(id) ON DELETE CASCADE,
    sheet_name       text,
    row_no           integer,
    severity         text NOT NULL CHECK (severity IN ('ERROR','WARNING','INFO')),
    code             text NOT NULL,
    field            text,
    message          text NOT NULL,
    value            text
);
CREATE INDEX ix_validation_issue_file ON metadata.validation_issue(file_id, severity);

CREATE TABLE metadata.dataset_version (
    id               bigserial PRIMARY KEY,
    file_id          bigint REFERENCES metadata.ingestion_file(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    description      text,
    line_items       integer,
    is_current       boolean NOT NULL DEFAULT false
);

CREATE TABLE metadata.data_refresh (
    id               bigserial PRIMARY KEY,
    file_id          bigint REFERENCES metadata.ingestion_file(id),
    refreshed_at     timestamptz NOT NULL DEFAULT now(),
    duration_ms      integer,
    data_version     bigint NOT NULL
);

CREATE TABLE metadata.app_setting (
    key              text PRIMARY KEY,
    value            jsonb NOT NULL,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Original dashboard figures (1.0) kept read-only for KPI reconciliation. NOT used to render the dashboard.
CREATE TABLE metadata.legacy_baseline (
    id               bigserial PRIMARY KEY,
    level            text NOT NULL CHECK (level IN ('overview','division','institute','department','equipment')),
    name             text NOT NULL,
    parent           text,
    metrics          jsonb NOT NULL,
    UNIQUE (level, name, parent)
);

CREATE TABLE metadata.app_user (
    id                bigserial PRIMARY KEY,
    username          text NOT NULL UNIQUE,
    full_name         text,
    password_hash     text NOT NULL,
    role              text NOT NULL CHECK (role IN ('admin','data_manager','analyst','viewer')),
    allowed_divisions text[],                    -- NULL = all divisions
    is_active         boolean NOT NULL DEFAULT true,
    failed_logins     integer NOT NULL DEFAULT 0,
    locked_until      timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_login_at     timestamptz
);

-- ============================================================ EQUIPMENT INVENTORY (line items)
CREATE TABLE equipment_inventory.line_item (
    id               bigserial PRIMARY KEY,
    business_key     char(40) NOT NULL UNIQUE,      -- sha1 of the standardised natural key
    institute_id     integer  NOT NULL REFERENCES master_data.institute(id),
    department_id    integer  NOT NULL REFERENCES master_data.department(id),
    equipment_id     integer  NOT NULL REFERENCES master_data.equipment(id),
    sub_category_id  integer  REFERENCES master_data.sub_category(id),
    course_category  text,
    department_type  text,
    cost_category    text,
    occurrence       smallint NOT NULL DEFAULT 1,     -- n-th repeat of the same natural key within a source file
    required_qty     integer  NOT NULL DEFAULT 0 CHECK (required_qty >= 0),
    available_qty    integer  NOT NULL DEFAULT 0 CHECK (available_qty >= 0),
    functional_qty   integer  NOT NULL DEFAULT 0 CHECK (functional_qty >= 0),
    non_functional_qty integer GENERATED ALWAYS AS (available_qty - functional_qty) STORED,
    row_hash         char(40) NOT NULL,
    is_active        boolean  NOT NULL DEFAULT true,
    source_file_id   bigint   REFERENCES metadata.ingestion_file(id),
    source_sheet     text,
    source_row       integer,
    raw_names        jsonb,                         -- original (un-standardised) names for traceability
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_li_inst_dept ON equipment_inventory.line_item(institute_id, department_id) WHERE is_active;
CREATE INDEX ix_li_equipment ON equipment_inventory.line_item(equipment_id) WHERE is_active;
CREATE INDEX ix_li_subcat ON equipment_inventory.line_item(sub_category_id) WHERE is_active;

-- ============================================================ PROCUREMENT / MAINTENANCE / LIFECYCLE (1:1 with line item)
CREATE TABLE procurement.procurement_proposal (
    line_item_id     bigint PRIMARY KEY REFERENCES equipment_inventory.line_item(id) ON DELETE CASCADE,
    proposed_qty     integer NOT NULL DEFAULT 0 CHECK (proposed_qty >= 0),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE maintenance.amc_coverage (
    line_item_id     bigint PRIMARY KEY REFERENCES equipment_inventory.line_item(id) ON DELETE CASCADE,
    amc_cmc_qty      integer NOT NULL DEFAULT 0 CHECK (amc_cmc_qty >= 0),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE lifecycle.lifecycle_status (
    line_item_id       bigint PRIMARY KEY REFERENCES equipment_inventory.line_item(id) ON DELETE CASCADE,
    end_of_life_qty    integer NOT NULL DEFAULT 0 CHECK (end_of_life_qty >= 0),
    condemnation_qty   integer NOT NULL DEFAULT 0 CHECK (condemnation_qty >= 0),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- ============================================================ FINANCIAL
CREATE TABLE financial.equipment_unit_cost (
    equipment_id     integer PRIMARY KEY REFERENCES master_data.equipment(id),
    unit_cost        numeric(18,2) NOT NULL CHECK (unit_cost >= 0),
    cost_category    text,
    source           text NOT NULL DEFAULT 'excel',
    source_file_id   bigint REFERENCES metadata.ingestion_file(id),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE financial.unit_cost_history (
    id               bigserial PRIMARY KEY,
    equipment_id     integer NOT NULL REFERENCES master_data.equipment(id),
    old_unit_cost    numeric(18,2),
    new_unit_cost    numeric(18,2),
    source_file_id   bigint REFERENCES metadata.ingestion_file(id),
    changed_at       timestamptz NOT NULL DEFAULT now()
);

-- ============================================================ STAGING
CREATE TABLE staging.inventory_row (
    id               bigserial PRIMARY KEY,
    file_id          bigint NOT NULL REFERENCES metadata.ingestion_file(id) ON DELETE CASCADE,
    sheet_name       text NOT NULL,
    row_no           integer NOT NULL,
    raw              jsonb NOT NULL,
    division         text, institute text, department text, equipment text, sub_category text,
    course_category  text, department_type text, cost_category text, bedded_capacity integer,
    required_qty     integer, available_qty integer, functional_qty integer, proposed_qty integer,
    amc_cmc_qty      integer, end_of_life_qty integer, condemnation_qty integer,
    unit_cost        numeric(18,2),
    business_key     char(40), row_hash char(40), occurrence smallint,
    status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','VALID','REJECTED')),
    loaded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_stg_inv_file ON staging.inventory_row(file_id, status);

CREATE TABLE staging.unit_cost_row (
    id               bigserial PRIMARY KEY,
    file_id          bigint NOT NULL REFERENCES metadata.ingestion_file(id) ON DELETE CASCADE,
    sheet_name       text NOT NULL,
    row_no           integer NOT NULL,
    raw              jsonb NOT NULL,
    equipment        text,
    unit_cost        numeric(18,2),
    cost_category    text,
    status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','VALID','REJECTED')),
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staging.institute_row (
    id               bigserial PRIMARY KEY,
    file_id          bigint NOT NULL REFERENCES metadata.ingestion_file(id) ON DELETE CASCADE,
    sheet_name       text NOT NULL,
    row_no           integer NOT NULL,
    raw              jsonb NOT NULL,
    institute        text, division text, bedded_capacity integer,
    status           text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','VALID','REJECTED')),
    loaded_at        timestamptz NOT NULL DEFAULT now()
);

-- ============================================================ AUDIT
CREATE TABLE audit.audit_log (
    id               bigserial PRIMARY KEY,
    occurred_at      timestamptz NOT NULL DEFAULT now(),
    actor            text NOT NULL,
    action           text NOT NULL,
    entity           text,
    entity_id        text,
    details          jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_ip        text
);
CREATE INDEX ix_audit_log_time ON audit.audit_log(occurred_at DESC);
CREATE INDEX ix_audit_log_action ON audit.audit_log(action);

CREATE TABLE audit.line_item_history (
    id               bigserial PRIMARY KEY,
    line_item_id     bigint NOT NULL,
    file_id          bigint,
    change_type      text NOT NULL CHECK (change_type IN ('INSERT','UPDATE','DEACTIVATE','REACTIVATE')),
    old_values       jsonb,
    new_values       jsonb,
    changed_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_li_hist_item ON audit.line_item_history(line_item_id);
CREATE INDEX ix_li_hist_file ON audit.line_item_history(file_id);

-- Audit log is append-only: block UPDATE/DELETE.
CREATE FUNCTION audit.block_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit tables are append-only'; END $$;
CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.block_mutation();

-- ============================================================ ANALYTICS
-- One enriched, denormalised fact row per ACTIVE line item. Every KPI in every module is an aggregate of this.
CREATE MATERIALIZED VIEW analytics.mv_line_fact AS
SELECT li.id                                   AS line_item_id,
       dv.id   AS division_id,   dv.name  AS division,
       ins.id  AS institute_id,  ins.name AS institute,  ins.bedded_capacity,
       dep.id  AS department_id, dep.name AS department,
       eq.id   AS equipment_id,  eq.name  AS equipment,
       sc.name AS sub_category,
       li.course_category, li.department_type,
       COALESCE(li.cost_category, uc.cost_category) AS cost_category,
       li.required_qty                          AS required,
       li.available_qty                         AS available,
       li.functional_qty                        AS functional,
       li.non_functional_qty                    AS non_functional,
       COALESCE(pp.proposed_qty, 0)             AS procurement,
       COALESCE(am.amc_cmc_qty, 0)              AS amc,
       COALESCE(lc.end_of_life_qty, 0)          AS end_of_life,
       COALESCE(lc.condemnation_qty, 0)         AS condemnation,
       uc.unit_cost                             AS unit_cost,
       (COALESCE(pp.proposed_qty, 0) * COALESCE(uc.unit_cost, 0))::numeric(20,2)                    AS budget,
       (li.required_qty - li.functional_qty)                                                         AS net_requirement,
       GREATEST(li.required_qty - li.functional_qty, 0)                                              AS functional_shortfall,
       (GREATEST(li.required_qty - li.functional_qty, 0) * COALESCE(uc.unit_cost, 0))::numeric(20,2) AS est_total_cost
FROM equipment_inventory.line_item li
JOIN master_data.institute  ins ON ins.id = li.institute_id
JOIN master_data.division   dv  ON dv.id  = ins.division_id
JOIN master_data.department dep ON dep.id = li.department_id
JOIN master_data.equipment  eq  ON eq.id  = li.equipment_id
LEFT JOIN master_data.sub_category sc ON sc.id = li.sub_category_id
LEFT JOIN procurement.procurement_proposal pp ON pp.line_item_id = li.id
LEFT JOIN maintenance.amc_coverage        am ON am.line_item_id = li.id
LEFT JOIN lifecycle.lifecycle_status      lc ON lc.line_item_id = li.id
LEFT JOIN financial.equipment_unit_cost   uc ON uc.equipment_id = li.equipment_id
WHERE li.is_active AND ins.is_active
WITH NO DATA;

CREATE UNIQUE INDEX ux_mv_line_fact ON analytics.mv_line_fact(line_item_id);
CREATE INDEX ix_mv_lf_division   ON analytics.mv_line_fact(division);
CREATE INDEX ix_mv_lf_institute  ON analytics.mv_line_fact(institute);
CREATE INDEX ix_mv_lf_department ON analytics.mv_line_fact(department);
CREATE INDEX ix_mv_lf_equipment  ON analytics.mv_line_fact(equipment);
CREATE INDEX ix_mv_lf_subcat     ON analytics.mv_line_fact(sub_category);
CREATE INDEX ix_mv_lf_bedded     ON analytics.mv_line_fact(bedded_capacity);

-- Convenience views (always consistent with mv_line_fact; same formulas everywhere)
CREATE VIEW analytics.v_division_kpi AS
SELECT division,
       sum(required) required, sum(available) available, sum(functional) functional,
       sum(non_functional) non_functional, sum(procurement) procurement,
       sum(required) - sum(functional) net_requirement, sum(budget) budget, sum(amc) amc,
       sum(condemnation) condemnation, sum(end_of_life) end_of_life,
       count(DISTINCT institute_id) college_count,
       CASE WHEN sum(required) > 0 THEN round(sum(functional)::numeric * 100 / sum(required), 2) ELSE 0 END utilisation_pct
FROM analytics.mv_line_fact GROUP BY division;

CREATE VIEW analytics.v_institute_kpi AS
SELECT division, institute, bedded_capacity,
       sum(required) required, sum(available) available, sum(functional) functional,
       sum(non_functional) non_functional, sum(procurement) procurement,
       sum(required) - sum(functional) net_requirement, sum(budget) budget, sum(amc) amc,
       sum(condemnation) condemnation, sum(end_of_life) end_of_life,
       CASE WHEN sum(required) > 0 THEN round(sum(functional)::numeric * 100 / sum(required), 2) ELSE 0 END utilisation_pct
FROM analytics.mv_line_fact GROUP BY division, institute, bedded_capacity;

-- ============================================================ SEED SETTINGS
INSERT INTO metadata.app_setting(key, value) VALUES
  ('data_version', '0'::jsonb),
  ('last_refresh', 'null'::jsonb),
  ('map', '{}'::jsonb);
"""


def upgrade() -> None:
    for s in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
    op.execute(DDL)
    # Grants for the read-only analytics role (created by scripts/init_db.sql). Guarded so migration works without it.
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'medd_readonly') THEN
        GRANT USAGE ON SCHEMA master_data, equipment_inventory, procurement, financial, maintenance,
                             lifecycle, analytics, metadata TO medd_readonly;
        GRANT SELECT ON ALL TABLES IN SCHEMA master_data, equipment_inventory, procurement, financial,
                             maintenance, lifecycle, analytics TO medd_readonly;
        GRANT SELECT ON metadata.app_setting, metadata.ingestion_file, metadata.data_refresh,
                        metadata.legacy_baseline, metadata.validation_issue, metadata.dataset_version TO medd_readonly;
        ALTER DEFAULT PRIVILEGES IN SCHEMA master_data, equipment_inventory, procurement, financial,
                             maintenance, lifecycle, analytics GRANT SELECT ON TABLES TO medd_readonly;
      END IF;
    END $$;
    """)


def downgrade() -> None:
    for s in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
