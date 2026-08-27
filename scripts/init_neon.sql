-- hwval schema bootstrap for Neon (or any managed Postgres).
--
-- Generated from the live SQLAlchemy metadata in src/hwval/db/models.py with:
--
--   from sqlalchemy.schema import CreateTable, CreateIndex
--   from sqlalchemy.dialects import postgresql
--   from hwval.db.models import Base
--   dialect = postgresql.dialect()
--   for table in Base.metadata.sorted_tables:
--       print(CreateTable(table).compile(dialect=dialect))
--       for index in table.indexes:
--           print(CreateIndex(index).compile(dialect=dialect))
--
-- i.e. this is byte-for-byte what `hwval init` (hwval.db.engine.init_db ->
-- Base.metadata.create_all) issues against Postgres -- provided here as a
-- plain .sql file for the case where you want to bootstrap a Neon branch
-- from the SQL editor / `psql` / a CI step, without a Python environment.
-- Verified against a real postgres:16 server: applies cleanly, and the
-- resulting table set matches Base.metadata.tables exactly.
--
-- Usage:
--   psql "$DATABASE_URL" -f scripts/init_neon.sql
--
-- where DATABASE_URL looks like:
--   postgresql://neondb_owner:***@ep-example-12345.us-east-2.aws.neon.tech/hwval?sslmode=require
--
-- Safe to run once against an empty database. It is NOT idempotent (no
-- IF NOT EXISTS / CREATE OR REPLACE) -- re-running it against a database
-- that already has these tables will error out, matching `hwval init`
-- (which drops first only when passed --drop). After this runs, seed data
-- and models still come from the application, not from SQL:
--
--   hwval seed --duts 60
--   hwval train
--   hwval score
--
-- (test_limit, test_plan and every row after that are populated by
-- hwval.db.seed.seed_database, not by this file -- this file only creates
-- the empty schema.)

BEGIN;

CREATE TABLE agent_audit (
	id SERIAL NOT NULL,
	ts TIMESTAMP WITH TIME ZONE NOT NULL,
	session_id VARCHAR(36) NOT NULL,
	tool_name VARCHAR(48) NOT NULL,
	arguments JSON NOT NULL,
	status VARCHAR(12) NOT NULL,
	latency_ms FLOAT NOT NULL,
	result_preview TEXT NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_agent_audit_tool_name ON agent_audit (tool_name);
CREATE INDEX ix_agent_audit_session_id ON agent_audit (session_id);
CREATE INDEX ix_agent_audit_ts ON agent_audit (ts);

CREATE TABLE dut (
	id SERIAL NOT NULL,
	serial VARCHAR(32) NOT NULL,
	part_number VARCHAR(32) NOT NULL,
	silicon_rev VARCHAR(8) NOT NULL,
	lot_id VARCHAR(16) NOT NULL,
	wafer_id INTEGER NOT NULL,
	die_x INTEGER NOT NULL,
	die_y INTEGER NOT NULL,
	package VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_dut_part_number ON dut (part_number);
CREATE INDEX ix_dut_lot_id ON dut (lot_id);
CREATE UNIQUE INDEX ix_dut_serial ON dut (serial);

CREATE TABLE maintenance_log (
	id SERIAL NOT NULL,
	ts TIMESTAMP WITH TIME ZONE NOT NULL,
	action VARCHAR(48) NOT NULL,
	target VARCHAR(96) NOT NULL,
	dry_run BOOLEAN NOT NULL,
	details JSON NOT NULL,
	duration_ms FLOAT NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_maintenance_log_ts ON maintenance_log (ts);
CREATE INDEX ix_maintenance_log_action ON maintenance_log (action);

CREATE TABLE test_limit (
	id SERIAL NOT NULL,
	param_name VARCHAR(32) NOT NULL,
	unit VARCHAR(8) NOT NULL,
	limit_low FLOAT NOT NULL,
	limit_high FLOAT NOT NULL,
	spec_ref VARCHAR(64) NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_test_limit_param_name ON test_limit (param_name);

CREATE TABLE test_plan (
	id SERIAL NOT NULL,
	name VARCHAR(96) NOT NULL,
	version VARCHAR(16) NOT NULL,
	standard_ref VARCHAR(64) NOT NULL,
	description TEXT NOT NULL,
	content_md TEXT NOT NULL,
	generated_by VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_testplan_name_version UNIQUE (name, version)
);
CREATE INDEX ix_test_plan_name ON test_plan (name);

CREATE TABLE test_run (
	id SERIAL NOT NULL,
	dut_id INTEGER NOT NULL,
	test_plan_id INTEGER,
	station_id VARCHAR(16) NOT NULL,
	operator VARCHAR(32) NOT NULL,
	firmware_version VARCHAR(16) NOT NULL,
	corner VARCHAR(16) NOT NULL,
	temp_setpoint_c FLOAT NOT NULL,
	supply_setpoint_v FLOAT NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	status VARCHAR(12) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_run_status CHECK (status in ('PASS','FAIL','ABORT')),
	FOREIGN KEY(dut_id) REFERENCES dut (id) ON DELETE CASCADE,
	FOREIGN KEY(test_plan_id) REFERENCES test_plan (id)
);
CREATE INDEX ix_test_run_started_at ON test_run (started_at);
CREATE INDEX ix_test_run_corner ON test_run (corner);
CREATE INDEX ix_test_run_status ON test_run (status);
CREATE INDEX ix_test_run_station_id ON test_run (station_id);
CREATE INDEX ix_test_run_dut_id ON test_run (dut_id);
CREATE INDEX ix_run_corner_started ON test_run (corner, started_at);

CREATE TABLE anomaly_event (
	id SERIAL NOT NULL,
	run_id INTEGER NOT NULL,
	detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
	model_name VARCHAR(48) NOT NULL,
	score FLOAT NOT NULL,
	severity VARCHAR(12) NOT NULL,
	param_name VARCHAR(32) NOT NULL,
	failure_mode VARCHAR(48) NOT NULL,
	explanation TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_sev CHECK (severity in ('LOW','MEDIUM','HIGH','CRITICAL')),
	FOREIGN KEY(run_id) REFERENCES test_run (id) ON DELETE CASCADE
);
CREATE INDEX ix_anomaly_event_run_id ON anomaly_event (run_id);
CREATE INDEX ix_anomaly_event_model_name ON anomaly_event (model_name);
CREATE INDEX ix_anomaly_event_severity ON anomaly_event (severity);

CREATE TABLE measurement (
	id SERIAL NOT NULL,
	run_id INTEGER NOT NULL,
	ts TIMESTAMP WITH TIME ZONE NOT NULL,
	sample_idx INTEGER NOT NULL,
	param_name VARCHAR(32) NOT NULL,
	value FLOAT NOT NULL,
	unit VARCHAR(8) NOT NULL,
	passed BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id) REFERENCES test_run (id) ON DELETE CASCADE
);
CREATE INDEX ix_measurement_passed ON measurement (passed);
CREATE INDEX ix_measurement_param_name ON measurement (param_name);
CREATE INDEX ix_measurement_run_id ON measurement (run_id);
CREATE INDEX ix_meas_run_param_idx ON measurement (run_id, param_name, sample_idx);
CREATE INDEX ix_meas_param_ts ON measurement (param_name, ts);
CREATE INDEX ix_measurement_ts ON measurement (ts);

CREATE TABLE run_label (
	id SERIAL NOT NULL,
	run_id INTEGER NOT NULL,
	is_anomaly BOOLEAN NOT NULL,
	failure_mode VARCHAR(48) NOT NULL,
	labelled_by VARCHAR(32) NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(run_id) REFERENCES test_run (id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_run_label_run_id ON run_label (run_id);
CREATE INDEX ix_run_label_failure_mode ON run_label (failure_mode);
CREATE INDEX ix_run_label_is_anomaly ON run_label (is_anomaly);

COMMIT;
