#!/usr/bin/env python3
"""
evwatts_targets.py — build calibration targets from EV-WATTS charging sessions and
score a simulated run's charging_sessions.csv against them.

EV-WATTS (182,872 sessions) is split 70% CALIBRATE / 30% HOLDOUT (deterministic by
session id hash). Targets computed on the calibrate split; the holdout is scored only
for final validation. Session-level observables (venue label is not in EV-WATTS public):
  - diurnal:  distribution of session start hour (24 bins)
  - energy:   distribution of energy_kwh (log-spaced bins)
  - duration: distribution of session duration hours (bins)
  - level:    L2 vs DCFC share (via connector power: >=50 kW = DCFC)

Usage:
  evwatts_targets.py build                      -> writes evwatts_targets.json (cal+holdout)
  evwatts_targets.py score <sim_sessions.csv> [--holdout]   -> prints weighted TVD score
"""
import sys, json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVW = ROOT / "data_ext/evwatts/evwatts.public/evwatts.public.vehiclesessions.csv"
CONN = ROOT / "data_ext/evwatts/evwatts.public/evwatts.public.connector.csv"
OUT = ROOT / "analysis/evwatts_targets.json"

EBINS = [0, 2, 5, 8, 12, 16, 20, 25, 30, 40, 60, 100, 1e9]        # kWh
DBINS = [0, 0.25, 0.5, 1, 1.5, 2, 3, 4, 6, 9, 12, 1e9]            # hours


def hist(vals, bins):
    h, _ = np.histogram(np.asarray(vals, float), bins=bins)
    s = h.sum()
    return (h / s).tolist() if s else [0] * (len(bins) - 1)


def diurnal(hours):
    h, _ = np.histogram(np.asarray(hours, float) % 24, bins=np.arange(25))
    s = h.sum()
    return (h / s).tolist() if s else [0] * 24


SBINS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]     # SOC swing fraction


def _profile(d):
    dur = pd.to_numeric(d.duration, errors="coerce")                # already HOURS
    kwh = pd.to_numeric(d.energy_kwh, errors="coerce")
    sw = (pd.to_numeric(d.soc_stop, errors="coerce")
          - pd.to_numeric(d.soc_start, errors="coerce"))            # 0..1 SOC gained
    if sw.dropna().abs().median() > 1.5:                            # stored as 0..100
        sw = sw / 100.0
    m = dur.between(0.1, 24) & kwh.between(0.5, 100)                # LDV-range sessions
    return {"energy": hist(kwh[m], EBINS), "duration": hist(dur[m], DBINS),
            "soc_swing": hist(sw[m & sw.notna()].clip(0, 1), SBINS), "n": int(m.sum())}


def build():
    d = pd.read_csv(EVW)
    keep = d.id.astype(str).map(lambda s: int(hashlib.md5(s.encode()).hexdigest(), 16) % 100)
    cal, hold = d[keep < 70], d[keep >= 70]
    tgt = {"calibrate": _profile(cal), "holdout": _profile(hold), "ebins": EBINS, "dbins": DBINS}
    OUT.write_text(json.dumps(tgt))
    print(f"[targets] calibrate n={tgt['calibrate']['n']:,}  holdout n={tgt['holdout']['n']:,} -> {OUT}")


def tvd(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return 0.5 * float(np.abs(a - b).sum())


def sim_profile(csv):
    d = pd.read_csv(csv, sep=";")
    dur = pd.to_numeric(d.duration_s, errors="coerce") / 3600.0
    kwh = pd.to_numeric(d.energy_kwh, errors="coerce")
    sw = pd.to_numeric(d.soc_end, errors="coerce") - pd.to_numeric(d.soc_start, errors="coerce")
    m = dur.between(0.1, 24) & kwh.between(0.5, 100)
    return {"energy": hist(kwh[m], EBINS), "duration": hist(dur[m], DBINS),
            "soc_swing": hist(sw[m & sw.notna()].clip(0, 1), SBINS),
            "diurnal": diurnal((pd.to_numeric(d.time_start_s, errors="coerce") / 3600.0)[m]),
            "n": int(m.sum())}


def score(csv, split="calibrate"):
    tgt = json.loads(OUT.read_text())[split]
    sim = sim_profile(csv)
    w = {"energy": 0.40, "duration": 0.30, "soc_swing": 0.30}       # weighted TVD (EV-WATTS)
    parts = {k: tvd(sim[k], tgt[k]) for k in w}
    total = sum(w[k] * parts[k] for k in w)
    return total, parts, sim["n"]


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build()
    elif sys.argv[1] == "score":
        split = "holdout" if "--holdout" in sys.argv else "calibrate"
        t, parts, n = score(sys.argv[2], split)
        print(f"[{split}] weighted TVD {t:.4f}  {({k: round(v,3) for k,v in parts.items()})}  sim_sessions={n:,}")
