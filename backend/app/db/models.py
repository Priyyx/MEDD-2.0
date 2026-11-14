"""SQLAlchemy ORM models (mirror of alembic/versions/0001_initial_schema.py).

Bulk ingestion and analytics use SQLAlchemy Core with parameterised SQL for performance; these models are used
for authentication, bookkeeping, admin endpoints and as Alembic autogenerate metadata for future migrations.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (ARRAY, BigInteger, Boolean, CHAR, Computed, DateTime, ForeignKey, Integer, Numeric,
                        SmallInteger, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ----------------------------------------------------------------- master_data
class Division(Base):
    __tablename__ = "division"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    map_key: Mapped[Optional[str]] = mapped_column(Text, unique=True)
    map_cx: Mapped[Optional[float]] = mapped_column(Numeric(8, 1))
    map_cy: Mapped[Optional[float]] = mapped_column(Numeric(8, 1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class District(Base):
    __tablename__ = "district"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    division_id: Mapped[int] = mapped_column(ForeignKey("master_data.division.id"))
    svg_path: Mapped[str] = mapped_column(Text)
    label_x: Mapped[Optional[float]] = mapped_column(Numeric(8, 1))
    label_y: Mapped[Optional[float]] = mapped_column(Numeric(8, 1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Institute(Base):
    __tablename__ = "institute"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    name_key: Mapped[str] = mapped_column(Text, unique=True)
    division_id: Mapped[int] = mapped_column(ForeignKey("master_data.division.id"))
    bedded_capacity: Mapped[Optional[int]] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text, default="excel")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Department(Base):
    __tablename__ = "department"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    name_key: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_key: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubCategory(Base):
    __tablename__ = "sub_category"
    __table_args__ = {"schema": "master_data"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NameAlias(Base):
    __tablename__ = "name_alias"
    __table_args__ = (UniqueConstraint("entity_type", "alias_key"), {"schema": "master_data"})
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text)
    alias_key: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(Text, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ----------------------------------------------------------------- metadata
class IngestionFile(Base):
    __tablename__ = "ingestion_file"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    original_name: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[Optional[str]] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text)
    dataset_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    sync_mode: Mapped[Optional[str]] = mapped_column(Text)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    rows_deactivated: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    report_path: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(Text, default="watcher")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class IngestionSheet(Base):
    __tablename__ = "ingestion_sheet"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("metadata.ingestion_file.id", ondelete="CASCADE"))
    sheet_name: Mapped[str] = mapped_column(Text)
    dataset_type: Mapped[str] = mapped_column(Text)
    header_row: Mapped[Optional[int]] = mapped_column(Integer)
    column_map: Mapped[dict] = mapped_column(JSONB, default=dict)
    unmapped_columns: Mapped[list] = mapped_column(JSONB, default=list)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)


class ValidationIssue(Base):
    __tablename__ = "validation_issue"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("metadata.ingestion_file.id", ondelete="CASCADE"))
    sheet_name: Mapped[Optional[str]] = mapped_column(Text)
    row_no: Mapped[Optional[int]] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    field: Mapped[Optional[str]] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[Optional[str]] = mapped_column(Text)


class DatasetVersion(Base):
    __tablename__ = "dataset_version"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("metadata.ingestion_file.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    description: Mapped[Optional[str]] = mapped_column(Text)
    line_items: Mapped[Optional[int]] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)


class DataRefresh(Base):
    __tablename__ = "data_refresh"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("metadata.ingestion_file.id"))
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    data_version: Mapped[int] = mapped_column(BigInteger)


class AppSetting(Base):
    __tablename__ = "app_setting"
    __table_args__ = {"schema": "metadata"}
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LegacyBaseline(Base):
    __tablename__ = "legacy_baseline"
    __table_args__ = (UniqueConstraint("level", "name", "parent"), {"schema": "metadata"})
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    level: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    parent: Mapped[Optional[str]] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB)


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = {"schema": "metadata"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[Optional[str]] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    allowed_divisions: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ----------------------------------------------------------------- inventory & satellites
class LineItem(Base):
    __tablename__ = "line_item"
    __table_args__ = {"schema": "equipment_inventory"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_key: Mapped[str] = mapped_column(CHAR(40), unique=True)
    institute_id: Mapped[int] = mapped_column(ForeignKey("master_data.institute.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("master_data.department.id"))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("master_data.equipment.id"))
    sub_category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("master_data.sub_category.id"))
    course_category: Mapped[Optional[str]] = mapped_column(Text)
    department_type: Mapped[Optional[str]] = mapped_column(Text)
    cost_category: Mapped[Optional[str]] = mapped_column(Text)
    occurrence: Mapped[int] = mapped_column(SmallInteger, default=1)
    required_qty: Mapped[int] = mapped_column(Integer, default=0)
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
    functional_qty: Mapped[int] = mapped_column(Integer, default=0)
    non_functional_qty: Mapped[int] = mapped_column(Integer, Computed("available_qty - functional_qty", persisted=True))
    row_hash: Mapped[str] = mapped_column(CHAR(40))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("metadata.ingestion_file.id"))
    source_sheet: Mapped[Optional[str]] = mapped_column(Text)
    source_row: Mapped[Optional[int]] = mapped_column(Integer)
    raw_names: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProcurementProposal(Base):
    __tablename__ = "procurement_proposal"
    __table_args__ = {"schema": "procurement"}
    line_item_id: Mapped[int] = mapped_column(ForeignKey("equipment_inventory.line_item.id", ondelete="CASCADE"), primary_key=True)
    proposed_qty: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AmcCoverage(Base):
    __tablename__ = "amc_coverage"
    __table_args__ = {"schema": "maintenance"}
    line_item_id: Mapped[int] = mapped_column(ForeignKey("equipment_inventory.line_item.id", ondelete="CASCADE"), primary_key=True)
    amc_cmc_qty: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LifecycleStatus(Base):
    __tablename__ = "lifecycle_status"
    __table_args__ = {"schema": "lifecycle"}
    line_item_id: Mapped[int] = mapped_column(ForeignKey("equipment_inventory.line_item.id", ondelete="CASCADE"), primary_key=True)
    end_of_life_qty: Mapped[int] = mapped_column(Integer, default=0)
    condemnation_qty: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EquipmentUnitCost(Base):
    __tablename__ = "equipment_unit_cost"
    __table_args__ = {"schema": "financial"}
    equipment_id: Mapped[int] = mapped_column(ForeignKey("master_data.equipment.id"), primary_key=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2))
    cost_category: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="excel")
    source_file_id: Mapped[Optional[int]] = mapped_column(ForeignKey("metadata.ingestion_file.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "audit"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    entity: Mapped[Optional[str]] = mapped_column(Text)
    entity_id: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    client_ip: Mapped[Optional[str]] = mapped_column(Text)
