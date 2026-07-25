"""Discretized-magnitude trip representation — a FULLY CATEGORICAL plain CVAE.

The single-Gaussian numeric heads under-disperse the heavy distance tail (VMT
undershoots). Here every magnitude (log-distance, travel, dwell) is binned into
CATEGORICAL log-bands, exactly like age/departure/kchain — a softmax head can
reproduce ANY marginal shape, including the heavy tail, so sampled VMT matches.
Decoding samples uniformly within a band in log space (-> expm1). Feasibility is
still enforced by a dwell-scaling repair. Both count (kchain) and magnitudes are
categorical, so the trip CVAE has NO numeric heads at all.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from src.trips import (K_MAX, PAD, HOME, DAY, DEP_BIN, N_DEP_BINS,   # noqa: E402
                       COND_CAT, COND_NUM, _si, build_daytable)

MAGS = ["logdist", "travel"]               # magnitude bands (dwell is DERIVED, not modelled)
N_MAG_BINS = 48

# ACTIVITY-TIME model: each trip's DEPARTURE is its own categorical half-hour band
# (depb_s), learned directly like distance — not derived cumulatively. This reproduces
# the AM/PM/midday departure profile by construction; dwell = gap between consecutive
# activities is derived at decode. Monotone order enforced in repair (sort by departure).
SLOT_CAT = ([f"{p}_{s}" for s in range(K_MAX) for p in ("act", "mode")]
            + [f"{m}b_{s}" for s in range(K_MAX) for m in MAGS]
            + [f"depb_{s}" for s in range(K_MAX)]
            + ["kchain"])
SLOT_NUM: list = []                          # fully categorical


def _logval(day, m, s):
    v = pd.to_numeric(day[f"{m}_{s}"], errors="coerce").to_numpy(float)
    return v if m == "logdist" else np.log1p(np.clip(v, 0, None))   # logdist already log1p


def fit_edges(day):
    """Fixed-width log-space bin edges per magnitude (geometric value spacing —
    fine at short trips, resolves the long tail)."""
    edges = {}
    for m in MAGS:
        vals = np.concatenate([_logval(day, m, s) for s in range(K_MAX)])
        vals = vals[~np.isnan(vals)]
        lo, hi = np.percentile(vals, 0.05), np.percentile(vals, 99.95)
        edges[m] = np.linspace(lo, hi, N_MAG_BINS + 1).tolist()
    return edges


def add_bands(day, edges):
    for m in MAGS:
        e = np.array(edges[m])
        for s in range(K_MAX):
            lv = _logval(day, m, s)
            b = np.clip(np.digitize(lv, e[1:-1]), 0, N_MAG_BINS - 1).astype(float)
            b[np.isnan(lv)] = -1                 # PAD sentinel category
            day[f"{m}b_{s}"] = b.astype(int)
    for s in range(K_MAX):                        # per-trip departure half-hour band
        d = pd.to_numeric(day[f"dep_{s}"], errors="coerce").to_numpy(float)
        b = np.clip(d // DEP_BIN, 0, N_DEP_BINS - 1)
        b[np.isnan(d)] = -1
        day[f"depb_{s}"] = b.astype(int)
    return day


def build(trip, ids, edges):
    return add_bands(build_daytable(trip, ids), edges)


def _band_to_val(b, m, edges, rng):
    e = edges[m]; b = min(max(_si(b, 0), 0), N_MAG_BINS - 1)
    lo, hi = e[b], e[b + 1]
    return float(np.expm1(lo + rng.random() * (hi - lo)))


def repair_disc(dec, i, edges, rng):
    """Feasible trip list from an ACTIVITY-TIME decoded sample. Each trip's departure is
    decoded from its own half-hour band; the departure VALUES are sorted and re-assigned
    to slots in order (slot 0 = earliest departure), while activities/modes/distances keep
    their slot order (home-anchored chain, last = home). This wins on all four at once:
    the departure profile is exactly preserved, activities stay ordered, departures are
    monotone by construction, and dwell = the (now-consistent) gap to the next trip."""
    acts = [_si(dec[f"act_{s}"][i]) for s in range(K_MAX)]
    n_nonpad = sum(1 for a in acts if a != PAD)
    k = min(max(_si(dec["kchain"][i], n_nonpad or 1), 1), K_MAX)
    segs, deps, prev_act = [], [], 2
    for j in range(k):
        act = acts[j] if acts[j] != PAD else prev_act
        prev_act = act
        db = _si(dec[f"depb_{j}"][i], -1)
        dep = (rng.uniform(6 * 60, 9 * 60) if db < 0                     # PAD -> AM fallback
               else db * DEP_BIN + rng.random() * DEP_BIN)               # within-band uniform
        deps.append(min(dep, DAY - 1))
        dist = min(max(_band_to_val(dec[f"logdistb_{j}"][i], "logdist", edges, rng), 0.1), 200.0)
        travel = min(max(_band_to_val(dec[f"travelb_{j}"][i], "travel", edges, rng), 1.0), 600.0)
        segs.append([act, _si(dec[f"mode_{j}"][i]), dist, travel])
    deps.sort()                                                         # monotone departure times
    segs[-1][0] = HOME                                                   # close the chain at home
    trips = []
    for j, (act, mode, dist, travel) in enumerate(segs):
        dep = deps[j]
        if j > 0:
            dep = max(dep, trips[-1]["arr_min"])                         # no time travel
        travel = max(5.0, round(travel / 5.0) * 5.0)
        arr = min(dep + travel, DAY)
        trips.append(dict(activity=act, mode=mode, distance=dist,
                          dep_min=round(dep), arr_min=round(arr), dwell_min=0.0))
    for j in range(len(trips) - 1):                                      # dwell = gap to next trip
        trips[j]["dwell_min"] = round(max(0.0, trips[j + 1]["dep_min"] - trips[j]["arr_min"]))
    return trips
