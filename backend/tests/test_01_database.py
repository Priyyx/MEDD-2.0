"""Initial database creation & migration, roles and constraints."""
import psycopg
import pytest
from sqlalchemy import text

from app.db.session import read_engine, write_engine

SCHEMAS = {"master_data", "equipment_inventory", "procurement", "financial", "maintenance", "lifecycle", "analytics",
           "staging", "metadata", "audit"}


def test_all_ten_schemas_exist():
    with write_engine.connect() as c:
        got = {r[0] for r in c.execute(text("SELECT schema_name FROM information_schema.schemata"))}
    assert SCHEMAS <= got


def test_hierarchy_tables_and_fks():
    with write_engine.connect() as c:
        fks = {(r[0], r[1]) for r in c.execute(text("""
            SELECT tc.table_name, ccu.table_name FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'"""))}
    for child, parent in [("district", "division"), ("institute", "division"), ("line_item", "institute"),
                          ("line_item", "department"), ("line_item", "equipment"), ("procurement_proposal", "line_item"),
                          ("amc_coverage", "line_item"), ("lifecycle_status", "line_item"), ("equipment_unit_cost", "equipment")]:
        assert (child, parent) in fks, (child, parent)


def test_reference_data_migrated():
    with read_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM master_data.division")).scalar() == 6
        assert c.execute(text("SELECT count(*) FROM master_data.district")).scalar() == 35
        assert c.execute(text("SELECT count(*) FROM master_data.institute")).scalar() == 35
        assert c.execute(text("SELECT count(*) FROM metadata.legacy_baseline")).scalar() == 1149


def test_readonly_role_cannot_write_or_read_secrets():
    with read_engine.connect() as c:
        with pytest.raises(Exception):
            c.execute(text("INSERT INTO master_data.sub_category(name) VALUES ('x')"))
    with read_engine.connect() as c:
        with pytest.raises(Exception):
            c.execute(text("SELECT password_hash FROM metadata.app_user"))


def test_quantity_constraints_reject_negative():
    with write_engine.begin() as c:
        ids = c.execute(text("SELECT (SELECT min(id) FROM master_data.institute), (SELECT min(id) FROM master_data.department), "
                             "(SELECT min(id) FROM master_data.equipment)")).one()
    with pytest.raises(Exception):
        with write_engine.begin() as c:
            c.execute(text("""INSERT INTO equipment_inventory.line_item(business_key, institute_id, department_id, equipment_id,
                              required_qty, row_hash) VALUES (repeat('a',40), :i, :d, :e, -1, repeat('b',40))"""),
                      {"i": ids[0], "d": ids[1], "e": ids[2]})


def test_audit_log_is_append_only():
    with write_engine.begin() as c:
        c.execute(text("INSERT INTO audit.audit_log(actor, action) VALUES ('test', 'X')"))
    with pytest.raises(Exception):
        with write_engine.begin() as c:
            c.execute(text("DELETE FROM audit.audit_log WHERE actor='test'"))


def test_migration_is_idempotent():
    from alembic import command
    from alembic.config import Config
    from tests.conftest import BACKEND
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")   # no-op, must not fail
