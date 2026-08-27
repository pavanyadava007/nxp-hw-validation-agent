"""Synthetic — but physically plausible — validation measurement generator.

The point of this module is that the anomaly labels are *causal*, not random:
each injected failure mode perturbs the underlying device physics and the
observable parameters follow from that, so a model has something real to learn.

Device model
------------
    P_dyn   = VDD_CORE * ICC                       (dynamic power, W)
    T_j     = T_amb + Rth_ja * P_dyn               (junction temperature, degC)
    I_leak  = I0 * 2 ** ((T_j - 25) / 15)          (sub-threshold leakage doubles
                                                    roughly every 15 K)
    ICC     = ICC_dyn(f, VDD) + I_leak             (closes the electro-thermal loop)
    jitter  = j0 * (1 + a*(T_j-25)) * (1 + b*ripple/VDD)

The loop is iterated per sample, so a supply droop really does show up as a
current rise, a temperature rise and a jitter rise — the correlation structure
an anomaly detector is supposed to exploit.
"""
from __future__ import annotations

import datetime as dt
import math
import random
from dataclasses import dataclass

import numpy as np

from hwval.config import get_settings
from hwval.db.engine import get_engine, init_db, session_scope
from hwval.db.models import DUT, Measurement, RunLabel, TestLimit, TestPlan, TestRun

PART_NUMBERS = ["S32K344", "i.MX93", "MPC5748G", "SJA1110"]
STATIONS = ["ATE-01", "ATE-02", "BENCH-A", "BENCH-B"]

# corner name -> (T_amb degC, VDD_CORE setpoint V)
CORNERS: dict[str, tuple[float, float]] = {
    "COLD_LOWV": (-40.0, 0.76),
    "COLD_NOMV": (-40.0, 0.80),
    "ROOM_NOMV": (25.0, 0.80),
    "ROOM_HIGHV": (25.0, 0.84),
    "HOT_NOMV": (125.0, 0.80),
    "HOT_HIGHV": (125.0, 0.84),
}

FAILURE_MODES = [
    "nominal",
    "vdd_droop",
    "thermal_runaway",
    "ldo_ripple",
    "clock_jitter_drift",
    "iddq_leakage_shift",
]

LIMITS: list[tuple[str, str, float, float, str]] = [
    ("VDD_CORE_V", "V", 0.740, 0.880, "Core supply, DS table 12"),
    ("VDD_IO_V", "V", 1.710, 1.890, "IO supply 1.8 V +/- 5%"),
    ("ICC_MA", "mA", 0.0, 420.0, "Total supply current"),
    ("TJ_C", "degC", -45.0, 150.0, "Junction temperature (AEC-Q100 Grade 1)"),
    ("CLK_MHZ", "MHz", 396.0, 404.0, "PLL output 400 MHz +/- 1%"),
    ("JITTER_PS", "ps", 0.0, 45.0, "Period jitter, RMS"),
    ("LEAK_UA", "uA", 0.0, 750.0, "IDDQ static leakage"),
    ("VOH_V", "V", 1.520, 1.890, "Output high level"),
]


@dataclass
class GenConfig:
    n_duts: int = 60
    runs_per_dut: int = 4
    samples_per_run: int = 48
    sample_period_s: float = 2.0
    anomaly_rate: float = 0.22
    glitch_rate: float = 0.07  # ATE glitches -> limit-screen false alarms
    days_history: int = 45
    seed: int = 42


# --------------------------------------------------------------------------
# physics core
# --------------------------------------------------------------------------
def _simulate_run(
    rng: np.random.Generator,
    t_amb: float,
    vdd_set: float,
    n: int,
    failure_mode: str,
    glitch: bool = False,
) -> dict[str, np.ndarray]:
    """Return per-sample arrays for one test run."""
    t = np.arange(n, dtype=float)
    frac = t / max(n - 1, 1)

    rth_ja = 22.0  # degC/W, typical LQFP junction-to-ambient thermal resistance
    i0_leak_ua = 2.4 * (1.0 + 0.15 * rng.standard_normal())  # IDDQ @25 degC, process spread
    icc_dyn_ma = 250.0 * (vdd_set / 0.80) ** 2 * (1.0 + 0.04 * rng.standard_normal())

    # --- failure-mode parameterisation ---------------------------------
    droop = np.zeros(n)
    ripple_amp = 0.0015 + 0.0005 * rng.random()  # nominal LDO ripple, V
    leak_mult = 1.0
    thermal_extra = np.zeros(n)
    jitter_extra = np.zeros(n)

    if failure_mode == "vdd_droop":
        onset = rng.integers(int(0.25 * n), int(0.6 * n))
        depth = rng.uniform(0.035, 0.075)
        droop = np.clip((t - onset) / max(n - onset, 1), 0, 1) ** 1.4 * depth
    elif failure_mode == "thermal_runaway":
        thermal_extra = 28.0 * frac**2.2 * rng.uniform(0.8, 1.4)
        leak_mult = 1.35
    elif failure_mode == "ldo_ripple":
        ripple_amp = rng.uniform(0.016, 0.030)
    elif failure_mode == "clock_jitter_drift":
        jitter_extra = 34.0 * frac ** rng.uniform(1.0, 1.8)
    elif failure_mode == "iddq_leakage_shift":
        step = rng.integers(int(0.2 * n), int(0.7 * n))
        leak_mult = np.where(t >= step, rng.uniform(3.0, 6.0), 1.0)

    ripple_f = rng.uniform(0.15, 0.45)
    ripple = ripple_amp * np.sin(2 * math.pi * ripple_f * t + rng.uniform(0, 6.28))

    vdd = vdd_set - droop + ripple + 0.0008 * rng.standard_normal(n)

    # electro-thermal fixed-point iteration (3 passes is plenty at this Rth)
    tj = np.full(n, t_amb + 6.0)
    icc = np.full(n, icc_dyn_ma)
    leak_ua = np.full(n, i0_leak_ua)
    for _ in range(3):
        leak_ua = i0_leak_ua * np.power(2.0, (tj - 25.0) / 15.0) * leak_mult
        icc = icc_dyn_ma * (vdd / 0.80) ** 2 + leak_ua / 1000.0
        p_dyn = vdd * icc / 1000.0  # W
        tj = t_amb + rth_ja * p_dyn + thermal_extra + 0.35 * rng.standard_normal(n)

    icc = icc + 1.8 * rng.standard_normal(n)
    leak_ua = np.clip(leak_ua + 6.0 * rng.standard_normal(n), 0, None)

    # PLL pulls weakly with supply and temperature (it locks to a crystal ref,
    # so the supply sensitivity shows up mostly as jitter, not as frequency)
    clk = 400.0 * (1 - 0.15 * (vdd_set - vdd)) - 0.0025 * (tj - 25.0)
    clk += 0.05 * rng.standard_normal(n)

    jitter = (
        14.0
        * (1 + 0.0045 * (tj - 25.0))
        * (1 + 60.0 * np.abs(ripple) / np.maximum(vdd, 1e-6))
        + jitter_extra
        + 0.7 * rng.standard_normal(n)
    )
    jitter = np.clip(jitter, 1.0, None)

    vdd_io = 1.80 + 0.004 * rng.standard_normal(n) - 0.35 * droop
    voh = vdd_io - 0.045 - 0.0004 * (tj - 25.0) + 0.004 * rng.standard_normal(n)

    out = {
        "VDD_CORE_V": vdd,
        "VDD_IO_V": vdd_io,
        "ICC_MA": icc,
        "TJ_C": tj,
        "CLK_MHZ": clk,
        "JITTER_PS": jitter,
        "LEAK_UA": leak_ua,
        "VOH_V": voh,
    }

    # ATE contact/handler glitch: a single-sample spike unrelated to any real
    # device defect. It trips the hard spec limit, so a naive limit screen
    # reports a FAIL ("overkill") where the device is actually healthy — this is
    # the noise the anomaly model is supposed to be robust to.
    if glitch:
        pname = ["VDD_CORE_V", "ICC_MA", "JITTER_PS", "LEAK_UA"][int(rng.integers(0, 4))]
        idx = int(rng.integers(1, n - 1))
        scale = {"VDD_CORE_V": -0.12, "ICC_MA": 260.0, "JITTER_PS": 55.0, "LEAK_UA": 1400.0}[pname]
        out[pname] = out[pname].copy()
        out[pname][idx] += scale

    return out


# --------------------------------------------------------------------------
# database population
# --------------------------------------------------------------------------
def seed_database(cfg: GenConfig | None = None, drop: bool = True, verbose: bool = True) -> dict:
    cfg = cfg or GenConfig()
    rng = np.random.default_rng(cfg.seed)
    random.seed(cfg.seed)

    init_db(drop=drop)
    limits = {name: (lo, hi) for name, _u, lo, hi, _d in LIMITS}
    units = {name: u for name, u, _lo, _hi, _d in LIMITS}

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    n_runs = 0
    n_meas = 0
    mode_counts: dict[str, int] = {m: 0 for m in FAILURE_MODES}

    with session_scope() as sess:
        for name, unit, lo, hi, desc in LIMITS:
            sess.add(
                TestLimit(param_name=name, unit=unit, limit_low=lo, limit_high=hi, description=desc)
            )
        plan = TestPlan(
            name="Characterisation over PVT corners",
            version="1.0",
            standard_ref="AEC-Q100 Grade 1",
            description="Baseline electrical characterisation across process, voltage, temperature.",
            content_md="(seeded baseline plan)",
            generated_by="human",
        )
        sess.add(plan)
        sess.flush()
        plan_id = plan.id

        for d in range(cfg.n_duts):
            dut = DUT(
                serial=f"SN{cfg.seed:02d}{d:05d}",
                part_number=random.choice(PART_NUMBERS),
                silicon_rev=random.choice(["A0", "A1", "B0"]),
                lot_id=f"LOT{1000 + d // 12}",
                wafer_id=int(rng.integers(1, 26)),
                die_x=int(rng.integers(0, 40)),
                die_y=int(rng.integers(0, 40)),
                package="LQFP144",
            )
            sess.add(dut)
            sess.flush()

            corners = random.sample(list(CORNERS), k=min(cfg.runs_per_dut, len(CORNERS)))
            for corner in corners:
                t_amb, vdd_set = CORNERS[corner]
                is_anom = rng.random() < cfg.anomaly_rate
                mode = random.choice(FAILURE_MODES[1:]) if is_anom else "nominal"
                mode_counts[mode] += 1

                start = now - dt.timedelta(
                    days=float(rng.uniform(0, cfg.days_history)),
                    minutes=float(rng.uniform(0, 1440)),
                )
                glitch = bool(rng.random() < cfg.glitch_rate)
                series = _simulate_run(rng, t_amb, vdd_set, cfg.samples_per_run, mode, glitch)

                rows: list[dict] = []
                any_fail = False
                for i in range(cfg.samples_per_run):
                    ts = start + dt.timedelta(seconds=cfg.sample_period_s * i)
                    for pname, arr in series.items():
                        lo, hi = limits[pname]
                        val = float(arr[i])
                        ok = lo <= val <= hi
                        any_fail |= not ok
                        rows.append(
                            {
                                "ts": ts,
                                "sample_idx": i,
                                "param_name": pname,
                                "value": round(val, 6),
                                "unit": units[pname],
                                "passed": ok,
                            }
                        )

                run = TestRun(
                    dut_id=dut.id,
                    test_plan_id=plan_id,
                    station_id=random.choice(STATIONS),
                    operator=random.choice(["auto", "p.yadava", "m.schmidt", "a.li"]),
                    firmware_version=random.choice(["1.4.2", "1.5.0", "2.0.1"]),
                    corner=corner,
                    temp_setpoint_c=t_amb,
                    supply_setpoint_v=vdd_set,
                    started_at=start,
                    ended_at=start
                    + dt.timedelta(seconds=cfg.sample_period_s * cfg.samples_per_run),
                    status="FAIL" if any_fail else "PASS",
                )
                sess.add(run)
                sess.flush()
                for r in rows:
                    r["run_id"] = run.id
                sess.bulk_insert_mappings(Measurement, rows)
                sess.add(
                    RunLabel(
                        run_id=run.id,
                        is_anomaly=mode != "nominal",
                        failure_mode=mode,
                        labelled_by="fa_lab",
                    )
                )
                n_runs += 1
                n_meas += len(rows)

            if verbose and (d + 1) % 20 == 0:
                print(f"  seeded {d + 1}/{cfg.n_duts} DUTs ...")

    stats = {
        "duts": cfg.n_duts,
        "runs": n_runs,
        "measurements": n_meas,
        "failure_modes": mode_counts,
        "dialect": get_engine().dialect.name,
    }
    if verbose:
        print(f"Seed complete: {stats}")
    return stats


if __name__ == "__main__":  # pragma: no cover
    get_settings()
    seed_database()
