# Test Plan: S32K344

## Scope

This plan defines the electrical characterization and validation test coverage for **S32K344**, targeting the following customer/program requirements:

> Supply-droop and thermal robustness over PVT corners

It covers PVT (process/voltage/temperature) corner sweeps, spec-limit pass/fail screening, and anomaly-detection regression, using the measurement warehouse defined in `hwval.db.models`.

## Applicable Standards

- Primary qualification standard: **AEC-Q100**
- Device grading and stress qualification follow the applicable AEC-Q100 grade for the target junction-temperature range (see Parameter/Limit table for `TJ_C`).
- Measurement traceability follows internal metrology calibration procedures; all limits are sourced from `test_limit.spec_ref`.

## DUT Configuration

- **Product:** S32K344
- **Package:** as bonded/packaged per the production flow (see `dut.package`).
- **Silicon revisions under test:** as recorded per DUT in `dut.silicon_rev`.
- **Sample size:** statistically representative sample per lot, spanning wafer position (die_x/die_y) to expose spatial process effects.
- **Test stations:** automated ATE and bench stations, logged per run (`test_run.station_id`).

## PVT Corner Matrix

| corner     |   temp_setpoint_c |   supply_setpoint_v |
|:-----------|------------------:|--------------------:|
| COLD_LOWV  |            -40.00 |                0.76 |
| COLD_NOMV  |            -40.00 |                0.80 |
| HOT_HIGHV  |            125.00 |                0.84 |
| HOT_NOMV   |            125.00 |                0.80 |
| ROOM_HIGHV |             25.00 |                0.84 |
| ROOM_NOMV  |             25.00 |                0.80 |

## Parameter / Limit Table

| param_name   | unit   |   limit_low |   limit_high | spec_ref   | description                             |
|:-------------|:-------|------------:|-------------:|:-----------|:----------------------------------------|
| CLK_MHZ      | MHz    |      396    |       404    | DS-REV-A   | PLL output 400 MHz +/- 1%               |
| ICC_MA       | mA     |        0    |       420    | DS-REV-A   | Total supply current                    |
| JITTER_PS    | ps     |        0    |        45    | DS-REV-A   | Period jitter, RMS                      |
| LEAK_UA      | uA     |        0    |       750    | DS-REV-A   | IDDQ static leakage                     |
| TJ_C         | degC   |      -45    |       150    | DS-REV-A   | Junction temperature (AEC-Q100 Grade 1) |
| VDD_CORE_V   | V      |        0.74 |         0.88 | DS-REV-A   | Core supply, DS table 12                |
| VDD_IO_V     | V      |        1.71 |         1.89 | DS-REV-A   | IO supply 1.8 V +/- 5%                  |
| VOH_V        | V      |        1.52 |         1.89 | DS-REV-A   | Output high level                       |

## Test Cases

### TC-001: Parametric sweep at COLD_LOWV

- **Setpoints:** T_amb = -40 degC, VDD_CORE = 0.76 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-002: Parametric sweep at COLD_NOMV

- **Setpoints:** T_amb = -40 degC, VDD_CORE = 0.80 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-003: Parametric sweep at HOT_HIGHV

- **Setpoints:** T_amb = 125 degC, VDD_CORE = 0.84 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-004: Parametric sweep at HOT_NOMV

- **Setpoints:** T_amb = 125 degC, VDD_CORE = 0.80 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-005: Parametric sweep at ROOM_HIGHV

- **Setpoints:** T_amb = 25 degC, VDD_CORE = 0.84 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-006: Parametric sweep at ROOM_NOMV

- **Setpoints:** T_amb = 25 degC, VDD_CORE = 0.80 V
- **Procedure:** power up DUT at the corner setpoints, allow thermal soak, then sample all tracked parameters continuously for the full run duration.
- **Parameters checked:** CLK_MHZ, ICC_MA, JITTER_PS, LEAK_UA, TJ_C, VDD_CORE_V, VDD_IO_V, VOH_V
- **Pass/fail:** every sample of every parameter must fall within its `test_limit` [limit_low, limit_high]; a single out-of-limit sample fails the run (see Pass/Fail Criteria).

### TC-007: Anomaly-robustness regression

- **Objective:** confirm the anomaly-detection model flags injected failure signatures (vdd_droop, thermal_runaway, ldo_ripple, clock_jitter_drift, iddq_leakage_shift) while not flagging a known-healthy run affected only by an ATE contact/handler glitch.
- **Procedure:** run `hwval.ml.predict.score_runs` over a held-out set of labelled runs (`run_label` table) and compare against the ground truth.
- **Pass/fail:** recall on true anomalies and false-alarm rate on glitch-only runs must both meet the thresholds in `hwval.ml.evaluate`.

## Pass/Fail Criteria

- A run is **PASS** iff every sampled value of every parameter is within `[limit_low, limit_high]` from the Parameter/Limit table above.
- A run is **FAIL** if any single sample violates its spec limit (hard limit screen); such a sample is also flagged `measurement.passed = false`.
- A run is **ABORT** if the station cannot complete the programmed sequence (handler jam, contact failure, loss of communication).
- An anomaly-model flag (`anomaly_event`) that does not correspond to a hard limit violation is reported as a **watch item**, not an automatic fail, and is routed to FA for disposition.

## Required Instrumentation

- ATE platform (or bench equivalent) capable of the corner supply/temperature setpoints in the PVT matrix above.
- Precision DC source/measure unit for VDD_CORE_V / VDD_IO_V with resolution better than 1/10 of the tightest spec margin.
- Thermal chamber or thermal forcing head spanning -40 degC to +125 degC.
- High-impedance probe or on-die monitor for JITTER_PS / CLK_MHZ.
- Picoammeter-class current measurement for LEAK_UA (IDDQ).

## Data Collection and Traceability Plan

- Every sample is written to `measurement` (one row per run/param/sample_idx), narrow/EAV schema so a new parameter never requires a schema migration.
- Every run is linked to its DUT, test plan, station, operator, and firmware version (`test_run`), giving full genealogy from a failing sample back to the exact device and program that produced it.
- Any FA disposition is recorded in `run_label` (ground truth, kept separate from model features to avoid train/serve leakage).
- Any automated tool invocation against this data is logged in `agent_audit`, and any destructive/maintenance action in `maintenance_log` -- required for audit in a certified validation lab.
- This test plan itself is versioned in `test_plan` (see `save_test_plan`), so every report can cite the exact plan revision it was generated against.

## Risk and Mitigation

| Risk | Mitigation |
|---|---|
| ATE contact/handler glitches produce single-sample false FAILs | Anomaly model cross-checks limit-screen fails against multi-parameter correlation before flagging a true excursion (see `plot_anomaly_scores`). |
| Thermal runaway undetected until hard TJ_C limit is hit | Continuous per-sample TJ_C monitoring plus trend-based anomaly scoring catches the ramp before the hard limit trips. |
| Process/wafer-position yield loss missed when viewed only in aggregate | Wafer map (die_x/die_y failure-rate heatmap) is generated every report cycle. |
| Test-plan drift between revisions breaks report comparability | `test_plan.name + version` is unique-constrained; `save_test_plan` bumps the version automatically instead of silently overwriting. |
| LLM-authored plan hallucinates limits or corners | Corner matrix and parameter/limit table are always pulled live from the database, never invented by the LLM; the deterministic template is the fallback on any LLM failure. |
