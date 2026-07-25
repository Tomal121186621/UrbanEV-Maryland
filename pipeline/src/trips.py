"""Trip-day representation + feasibility repair for the conditional trip CVAE.

A person-day is a FIXED-LENGTH vector of K_MAX slots. Each slot has an activity
(0 = PAD/end-of-day), a mode, and three numerics (log-distance, travel-min,
dwell-min); one global numeric is the first departure. Chain length is implicit:
the day ends at the first PAD slot. Feasibility is guaranteed by a decode-time
REPAIR (force last activity = home, derive monotone times, truncate on 24h
overflow), so 100% of generated chains are valid.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

K_MAX = 12
HOME = 1
PAD = 0
DAY = 24 * 60
DEP_BIN = 15                     # departure-time resolution (minutes) — fine bins keep the
N_DEP_BINS = DAY // DEP_BIN      # derived-dwell (gap between departures) quantization low

COND_CAT = ["home_county", "hh_income_detailed", "hhsize", "numworkers",
            "numvehicle", "license", "employment_status", "home_type", "gender"]
COND_NUM = ["age"]

# first departure is CATEGORICAL (half-hour band): the AM commute peak is a sharp
# mode a single Gaussian smooths away. Subsequent departures are cumulative, so a
# crisp first departure sharpens the whole departure-time profile.
# kchain = trip count is also CATEGORICAL: independent per-slot PAD heads truncate the
# long-chain tail (trips/person undershoot -> low VMT). Modelling the count directly
# (one more categorical output of the SAME plain decoder — not a separate count-head
# architecture) reproduces the true chain-length distribution incl. its tail.
SLOT_CAT = ([f"{p}_{s}" for s in range(K_MAX) for p in ("act", "mode")]
            + ["first_dep_band", "kchain"])
SLOT_NUM = [f"{p}_{s}" for s in range(K_MAX) for p in ("logdist", "travel", "dwell")]


def build_daytable(trip: pd.DataFrame, person_ids) -> pd.DataFrame:
    """One row per traveler person: padded K_MAX-slot day."""
    t = trip[trip.person_id.isin(person_ids)].sort_values(["person_id", "tripno"])
    rows = {}
    for pid, g in t.groupby("person_id", sort=False):
        g = g.head(K_MAX)
        r = {p: PAD for p in SLOT_CAT}
        # PAD-slot numerics are NaN (not 0): a stored 0 would pull each slot field's
        # z-score mean toward 0 (later slots are mostly PAD), so an occupied late slot
        # would decode to a near-zero distance. NaN is excluded from the codec's
        # occupied-only mean/std and neutral-filled (z=0) at encode time.
        for p in SLOT_NUM:
            r[p] = np.nan
        fd = float(g.dep_min.iloc[0])
        r["first_dep_band"] = int(min(max(fd // DEP_BIN, 0), N_DEP_BINS - 1))
        r["kchain"] = int(len(g))                       # trip count (already <= K_MAX)
        for s, (_, tr) in enumerate(g.iterrows()):
            r[f"act_{s}"] = int(tr.d_activity)
            r[f"mode_{s}"] = int(tr.travel_mode)
            # distance is modelled in LOG space (strong right-skew). travel/dwell are
            # kept in raw minutes: log-transforming them perturbed the shared decoder
            # and regressed the sim-critical distance/VMT for only a marginal (heaping-
            # dominated) travel-time TVD gain — net-negative, so reverted.
            r[f"logdist_{s}"] = float(np.log1p(tr.distance))
            r[f"travel_{s}"] = float(tr.travel_min)
            r[f"dwell_{s}"] = float(min(tr.dwell_min, DAY))
            r[f"dep_{s}"] = float(tr.dep_min)            # per-trip departure (activity-time model)
        rows[pid] = r
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "person_id"
    return df.reset_index()


def _si(x, default=PAD):
    """Safe int for decoded categoricals (codec may emit '__OOV__')."""
    s = str(x)
    return int(s) if s.lstrip("-").isdigit() else default


def repair_day(dec: dict, i: int):
    """Turn one decoded sample (dict of arrays) into a feasible trip list.
    Returns list of dicts: {activity, mode, distance, dep_min, arr_min, dwell_min}."""
    acts = [_si(dec[f"act_{s}"][i]) for s in range(K_MAX)]
    # Chain length is the DIRECTLY MODELLED categorical kchain (not the leading PAD run,
    # which truncates the tail). Trips occupy slots 0..k-1 in training; read them in
    # order. A rare PAD in an early slot (sampling noise) falls back to the previous
    # slot's activity so the count still honours kchain.
    n_nonpad = sum(1 for a in acts if a != PAD)
    k = _si(dec["kchain"][i], n_nonpad or 1)
    k = min(max(k, 1), K_MAX)
    if k == 0:
        return []
    # decode the categorical first-departure band -> minutes (band midpoint)
    fb = min(max(_si(dec["first_dep_band"][i], N_DEP_BINS // 3), 0), N_DEP_BINS - 1)
    dep0 = min(max(fb * DEP_BIN + DEP_BIN / 2.0, 0.0), DAY - 1)
    # gather k segments (act, mode, distance, travel, dwell)
    segs, prev_act = [], 2                                # 2 = generic non-home fallback
    for j in range(k):
        act = acts[j] if acts[j] != PAD else prev_act
        prev_act = act
        dist = min(max(float(np.expm1(dec[f"logdist_{j}"][i])), 0.1), 200.0)
        travel = min(max(float(dec[f"travel_{j}"][i]), 1.0), 600.0)
        dwell = min(max(float(dec[f"dwell_{j}"][i]), 0.0), DAY)
        segs.append([act, _si(dec[f"mode_{j}"][i]), dist, travel, dwell])
    segs[-1][0] = HOME                                    # close the chain at home
    # FEASIBILITY REPAIR: fit all k trips in <=24h by scaling the flexible parts
    # (intermediate dwells, then travels) rather than truncating trips — preserves the
    # modelled trip count and its VMT instead of dropping the tail on time overflow.
    sum_travel = sum(s[3] for s in segs)
    sum_dwell = sum(s[4] for s in segs[:-1])             # dwells before the final home
    avail = DAY - dep0 - sum_travel
    if avail <= 0 and sum_travel > 0:                    # travels alone overflow (rare)
        sc = max(0.0, DAY - dep0) / sum_travel
        for s in segs:
            s[3] *= sc
        sum_travel *= sc; avail = DAY - dep0 - sum_travel
    if sum_dwell > avail and sum_dwell > 0:              # compress dwells to fit
        sc = max(0.0, avail) / sum_dwell
        for s in segs[:-1]:
            s[4] *= sc
    # build cumulatively (guaranteed feasible now)
    trips, dep = [], dep0
    for j, (act, mode, dist, travel, dwell) in enumerate(segs):
        arr = min(dep + travel, DAY)
        dwell_use = 0.0 if j == len(segs) - 1 else dwell
        trips.append(dict(activity=act, mode=mode, distance=dist,
                          dep_min=dep, arr_min=arr, dwell_min=dwell_use))
        dep = min(arr + dwell_use, DAY)
    return trips
