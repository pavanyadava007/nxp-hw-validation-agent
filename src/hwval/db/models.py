"""SQLAlchemy ORM model of a semiconductor validation-lab data warehouse.

Grain notes (asked about in interviews):
  * ``dut``           – one row per physical die/package under test.
  * ``test_run``      – one row per (DUT, corner, station) execution.
  * ``measurement``   – narrow/EAV-style fact table, one row per sampled
                        parameter value. Narrow beats wide here because the
                        parameter set differs per test plan and per silicon
                        revision; adding a parameter must not be a DDL change.
  * ``anomaly_event`` – model output, one row per detected excursion.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class DUT(Base):
    """Device Under Test."""

    __tablename__ = "dut"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    part_number: Mapped[str] = mapped_column(String(32), index=True)
    silicon_rev: Mapped[str] = mapped_column(String(8))
    lot_id: Mapped[str] = mapped_column(String(16), index=True)
    wafer_id: Mapped[int] = mapped_column(Integer)
    die_x: Mapped[int] = mapped_column(Integer)
    die_y: Mapped[int] = mapped_column(Integer)
    package: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    runs: Mapped[list["TestRun"]] = relationship(back_populates="dut", cascade="all, delete-orphan")


class TestPlan(Base):
    __tablename__ = "test_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(96), index=True)
    version: Mapped[str] = mapped_column(String(16), default="1.0")
    standard_ref: Mapped[str] = mapped_column(String(64), default="AEC-Q100")
    description: Mapped[str] = mapped_column(Text, default="")
    content_md: Mapped[str] = mapped_column(Text, default="")
    generated_by: Mapped[str] = mapped_column(String(32), default="human")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (UniqueConstraint("name", "version", name="uq_testplan_name_version"),)


class TestRun(Base):
    __tablename__ = "test_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dut_id: Mapped[int] = mapped_column(ForeignKey("dut.id", ondelete="CASCADE"), index=True)
    test_plan_id: Mapped[int | None] = mapped_column(ForeignKey("test_plan.id"), nullable=True)
    station_id: Mapped[str] = mapped_column(String(16), index=True)
    operator: Mapped[str] = mapped_column(String(32), default="auto")
    firmware_version: Mapped[str] = mapped_column(String(16), default="0.0.0")
    corner: Mapped[str] = mapped_column(String(16), index=True)  # e.g. HOT_HIGHV
    temp_setpoint_c: Mapped[float] = mapped_column(Float)
    supply_setpoint_v: Mapped[float] = mapped_column(Float)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="PASS", index=True)  # PASS/FAIL/ABORT

    dut: Mapped[DUT] = relationship(back_populates="runs")
    measurements: Mapped[list["Measurement"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("status in ('PASS','FAIL','ABORT')", name="ck_run_status"),
        Index("ix_run_corner_started", "corner", "started_at"),
    )


class TestLimit(Base):
    """Spec limits per parameter — the single source of truth for pass/fail."""

    __tablename__ = "test_limit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    param_name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    unit: Mapped[str] = mapped_column(String(8))
    limit_low: Mapped[float] = mapped_column(Float)
    limit_high: Mapped[float] = mapped_column(Float)
    spec_ref: Mapped[str] = mapped_column(String(64), default="DS-REV-A")
    description: Mapped[str] = mapped_column(Text, default="")


class Measurement(Base):
    __tablename__ = "measurement"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_run.id", ondelete="CASCADE"), index=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    sample_idx: Mapped[int] = mapped_column(Integer)
    param_name: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(8))
    passed: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    run: Mapped[TestRun] = relationship(back_populates="measurements")

    __table_args__ = (
        Index("ix_meas_run_param_idx", "run_id", "param_name", "sample_idx"),
        Index("ix_meas_param_ts", "param_name", "ts"),
    )


class RunLabel(Base):
    """Failure-analysis disposition for a run.

    In a real lab this is filled in by the FA engineer after decap/curve-trace;
    here it is the injected ground truth. It is kept in its own table so the
    supervised model can never accidentally read its label out of the feature
    tables (train/serve skew is the classic way this project would go wrong).
    """

    __tablename__ = "run_label"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("test_run.id", ondelete="CASCADE"), unique=True, index=True
    )
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    failure_mode: Mapped[str] = mapped_column(String(48), default="nominal", index=True)
    labelled_by: Mapped[str] = mapped_column(String(32), default="fa_lab")


class AnomalyEvent(Base):
    __tablename__ = "anomaly_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_run.id", ondelete="CASCADE"), index=True)
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    model_name: Mapped[str] = mapped_column(String(48), index=True)
    score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(12), default="LOW", index=True)
    param_name: Mapped[str] = mapped_column(String(32), default="")
    failure_mode: Mapped[str] = mapped_column(String(48), default="unknown")
    explanation: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        CheckConstraint("severity in ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_sev"),
    )


class AgentAudit(Base):
    """Every tool invocation is logged — traceability is a certification
    requirement in a validation lab, and it is what makes an LLM agent
    auditable rather than a black box."""

    __tablename__ = "agent_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    tool_name: Mapped[str] = mapped_column(String(48), index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="ok")
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    result_preview: Mapped[str] = mapped_column(Text, default="")


class MaintenanceLog(Base):
    __tablename__ = "maintenance_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str] = mapped_column(String(96), default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)


ALL_TABLES = [
    DUT.__tablename__,
    TestPlan.__tablename__,
    TestRun.__tablename__,
    TestLimit.__tablename__,
    Measurement.__tablename__,
    RunLabel.__tablename__,
    AnomalyEvent.__tablename__,
    AgentAudit.__tablename__,
    MaintenanceLog.__tablename__,
]
