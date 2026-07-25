#!/usr/bin/env python3
"""Comprehensive per-scenario analysis engine — showcases the simulation + modeling power.
For any run it extracts, from the converged charging sessions joined to agent demographics:
  * energy / venue / charger-type shares            (charging behaviour)
  * battery SOC dynamics (start/end/depth, anxiety) (physics of the fleet)
  * session characteristics (duration, walk, size)  (access friction)
  * diurnal load profile, peak MW & hour, off-peak  (grid load, ToU response)
  * smart-charging / ToU shift                       (behavioural module)
  * demographic cross-tabs (income/tenure/age/PT/…)  (heterogeneity)
Writes one metrics row per scenario -> paper/tables/scenario_metrics_master.csv
and per-scenario demographic breakdowns  -> paper/tables/scen_<run>_breakdown.parquet
Run:  scenario_metrics.py [run1 run2 ...]   (default: all finished runs)"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
TAB = REPO / "paper/tables"; TAB.mkdir(parents=True, exist_ok=True)
DAYS = 348.0; PLAN = 3.0
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"

# ToU multiplier schedule (ChargingCostUtils.java) — for off-peak / grid analysis
def tou_mult(ts):
    m = int((ts // 60) % 1440)
    return (0.7 if m < 360 else 1.6 if m < 480 else 1.47 if m < 600 else
            0.92 if m < 1020 else 1.14 if m < 1200 else 1.0 if m < 1320 else 0.7)


def latest_sessions(run):
    fs = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    if not fs:
        return None, None
    d = pd.read_csv(fs[-1], sep=";")
    for c in ["energy_kwh", "soc_start", "soc_end", "duration_s", "walking_dist_m",
              "time_start_s", "value_of_time", "beta_money"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d, fs[-1].split("ITERS/")[1].split("/")[0]


DEMO = None
def demographics():
    global DEMO
    if DEMO is None:
        ev = pd.read_parquet(EVO)
        keep = ["person_id", "home_county", "home_type", "home_ownership", "hhsize",
                "numworkers", "gender", "age", "employment_status", "ev_powertrain"] \
            if "ev_powertrain" in ev.columns else \
            ["person_id", "home_county", "home_type", "home_ownership", "hhsize",
             "numworkers", "gender", "age", "employment_status"]
        DEMO = ev[[c for c in keep if c in ev.columns]].copy()
        DEMO["renter"] = (pd.to_numeric(DEMO.home_ownership, errors="coerce") == 2)
    return DEMO


def wmean(v, w):
    v, w = np.asarray(v, float), np.asarray(w, float)
    m = np.isfinite(v) & np.isfinite(w) & (w > 0)
    return float(np.average(v[m], weights=w[m])) if m.any() else np.nan


def analyze(run):
    d, it = latest_sessions(run)
    if d is None:
        print(f"[skip] {run}: no sessions"); return None
    e = d.energy_kwh
    ann = lambda kwh: kwh / PLAN * DAYS / 1e6                       # -> GWh/yr
    pub = d[d.charger_type_3way == "public"]; home = d[d.charger_type == "home"]
    d["hour"] = (d.time_start_s // 3600 % 24)
    d["mult"] = d.time_start_s.map(tou_mult)
    # diurnal load: kW per hour = energy in hour / hour, averaged over PLAN days
    load = d.groupby("hour").energy_kwh.sum() / PLAN                # kWh per hour-of-day (avg day)
    peak_mw = load.max() / 1e3; peak_hr = int(load.idxmax()) if len(load) else -1
    m = {
        "run": run, "iter": it, "n_sessions": len(d), "n_agents": int(d.person_id.nunique()),
        "energy_gwh_yr": round(ann(e.sum()), 1),
        # venue (energy %)
        "sh_home_e": round(home.energy_kwh.sum() / e.sum() * 100, 1),
        "sh_work_e": round(d[d.charger_type == "work"].energy_kwh.sum() / e.sum() * 100, 1),
        "sh_public_e": round(pub.energy_kwh.sum() / e.sum() * 100, 1),
        # charger type (energy %)
        "sh_L2_e": round(d[d.charger_type == "L2"].energy_kwh.sum() / e.sum() * 100, 1),
        "sh_DCFC_e": round(d[d.charger_type == "DCFC"].energy_kwh.sum() / e.sum() * 100, 1),
        "sh_Tesla_e": round(d[d.charger_type == "DCFC_TESLA"].energy_kwh.sum() / e.sum() * 100, 1),
        # SOC dynamics
        "soc_start_mean": round(d.soc_start.mean() * 100, 1),
        "soc_start_p10": round(d.soc_start.quantile(0.10) * 100, 1),
        "soc_end_mean": round(d.soc_end.mean() * 100, 1),
        "depth_mean_pp": round((d.soc_end - d.soc_start).mean() * 100, 1),
        "soc_start_public": round(pub.soc_start.mean() * 100, 1),
        # session characteristics
        "dur_home_min": round(home.duration_s.median() / 60, 1),
        "dur_public_min": round(pub.duration_s.median() / 60, 1),
        "kwh_per_session": round(e.mean(), 1),
        "kwh_per_agent_day": round(e.sum() / PLAN / d.person_id.nunique(), 1),
        "walk_public_m": round(pub.walking_dist_m.median(), 0),
        # grid / temporal
        "peak_mw": round(peak_mw, 1), "peak_hour": peak_hr,
        "offpeak_e_pct": round(d[d.mult == 0.7].energy_kwh.sum() / e.sum() * 100, 1),
        "smart_aware_pct": round(d.drop_duplicates("person_id").smart_aware.mean() * 100, 1)
            if "smart_aware" in d.columns else np.nan,
        # heterogeneity
        "vot_mean": round(wmean(d.value_of_time, d.energy_kwh), 1) if "value_of_time" in d.columns else np.nan,
    }
    # ---- demographic breakdown (per-agent energy joined to demographics) ----
    dem = demographics()
    pa = d.groupby("person_id").agg(energy=("energy_kwh", "sum"),
                                    pub_e=("energy_kwh", lambda x: x[d.loc[x.index, "charger_type_3way"] == "public"].sum()),
                                    soc_start=("soc_start", "mean"),
                                    n=("session_id", "size")).reset_index()
    pa = pa.merge(dem, on="person_id", how="left")
    pa["pub_share"] = pa.pub_e / pa.energy.clip(lower=1e-9) * 100
    pa["age_grp"] = pd.cut(pa.age, [0, 30, 45, 60, 200], labels=["<30", "30-45", "45-60", "60+"])
    pa.to_parquet(TAB / f"scen_{run}_breakdown.parquet")
    # summary cross-tabs into the metrics row
    if "renter" in pa:
        m["pubshare_renter"] = round(pa[pa.renter].pub_share.mean(), 1)
        m["pubshare_owner"] = round(pa[~pa.renter].pub_share.mean(), 1)
    return m


def main():
    runs = sys.argv[1:] or [p.name for p in sorted(RUNS.glob("*"))
                            if (p / "ITERS").is_dir() and p.name.startswith(("baseline_pertype", "policy_", "sweep_"))]
    rows = [r for r in (analyze(run) for run in runs) if r]
    if not rows:
        print("no finished runs to analyze"); return
    master = pd.DataFrame(rows)
    master.to_csv(TAB / "scenario_metrics_master.csv", index=False)
    cols = ["run", "iter", "n_agents", "energy_gwh_yr", "sh_home_e", "sh_public_e",
            "soc_start_mean", "soc_start_public", "peak_mw", "peak_hour", "offpeak_e_pct",
            "kwh_per_agent_day", "walk_public_m", "pubshare_renter", "pubshare_owner"]
    print(master[[c for c in cols if c in master.columns]].to_string(index=False))
    print(f"\n[done] {len(rows)} scenarios -> paper/tables/scenario_metrics_master.csv (+ per-run breakdowns)")


if __name__ == "__main__":
    main()
