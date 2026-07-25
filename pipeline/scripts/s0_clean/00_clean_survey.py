#!/usr/bin/env python3
"""
00_clean_survey.py — careful, transparent cleaning of the raw MD travel survey.

Raw: Upstream/EV Assignment Model/00__flat_data.csv (488,705 trip rows; the file
is jitter-resampled so ~33% of rows are near-duplicates). We clean from RAW (not
the old pre-processed parquets, which silently dropped ~40% of households).

Steps (each logged to cleaning_manifest.json):
  1. Load needed columns; dedup to one row per (person_id, tripno) -> 163,290 trips.
  2. Parse HHMM times -> minutes; derive travel_min, dwell_min.
  3. Zones: use TRACT FIPS (100% present; we have tract centroids). county = tract[:5].
  4. Missing (sentinel -9): impute employment_status (12%), license (4.9%) by group;
     impute hh_income_detailed (1.6%); drop rows with -9 in near-complete fields
     (age, gender, home_type, home_ownership, activity, distance).
  5. Feasibility per person: chain starts & ends at home; temporal monotonic;
     day budget <= 24h; 0 < distance <= 200 mi. Drop persons that fail.
  6. Emit survey_{hh,person,trip}.parquet + cleaning_manifest.json.

Activity codes (codebook): 1 Home,2 Work,3 Volunteer,4 School,5 Shopping,6 Meal-quick,
7 Meal,8 Gas,9 Healthcare,10 Errand,11 Socialize,12 Civic,13 Exercise,14 Recreation,
15 Entertainment,16 Dropoff/pickup,17 (change-mode),18 Other.
Mode codes: 1 Walk,2 Bike,3 Motorcycle,4 Auto-driver,5 Auto-passenger,6 SchoolBus,
7 Rail,8 Bus,9 PrivateBus,10 Paratransit,11 Taxi,12 TNC,13 Air,14 Water,15 Other.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
RAW = ROOT / "Upstream/EV Assignment Model/00__flat_data.csv"
GEO = ROOT / "pipeline/data/geo/tract_centroids.parquet"
OUT = ROOT / "pipeline/data/interim"
OUT.mkdir(parents=True, exist_ok=True)

HOME = 1  # activity code for Home
SENTINEL = -9
manifest = {"raw_file": str(RAW.relative_to(ROOT)), "steps": []}


def log(step, **kw):
    manifest["steps"].append({"step": step, **kw})
    print(f"[{step}] " + "  ".join(f"{k}={v}" for k, v in kw.items()), flush=True)


def hhmm_to_min(s):
    """Parse both 'HH:MM' (57% of rows) and 'HHMM'/'HMM' digit forms -> minutes."""
    s = str(s).strip()
    if ":" in s:
        p = s.split(":")
        try:
            return int(p[0]) * 60 + int(p[1])
        except (ValueError, IndexError):
            return np.nan
    if s.isdigit():
        v = int(s)
        return (v // 100) * 60 + (v % 100)
    return np.nan


def main():
    hh_cols = ["household_id", "home_tract_fips", "home_state_county_fips",
               "home_type", "home_ownership", "hhsize", "numworkers",
               "numvehicle", "numbicycle", "hh_income_detailed", "wthhfin"]
    per_cols = ["household_id", "person_id", "age", "gender", "license",
                "employment_status", "j1_telecommute", "j1_telecommute_days",
                "j1_benefits_ev_charging", "wtperfin"]
    trip_cols = ["household_id", "person_id", "tripno", "o_activity", "d_activity",
                 "travel_mode", "distance", "departure_time_hhmm",
                 "arrival_time_hhmm", "reported_travel_time",
                 "d_tract_fips", "d_state_county_fips", "wttrdfin"]
    use = sorted(set(hh_cols + per_cols + trip_cols))
    fips_str = {c: str for c in ["home_tract_fips", "home_state_county_fips",
                                 "d_tract_fips", "d_state_county_fips"]}
    df = pd.read_csv(RAW, usecols=use, dtype=fips_str, low_memory=False)
    log("load", rows=len(df), hh=df.household_id.nunique(), persons=df.person_id.nunique())

    # 1. dedup (person, tripno) — keep first
    df = df.drop_duplicates(["person_id", "tripno"], keep="first").reset_index(drop=True)
    log("dedup_person_tripno", rows=len(df))

    # 2. times
    df["dep_min"] = df.departure_time_hhmm.map(hhmm_to_min)
    df["arr_min"] = df.arrival_time_hhmm.map(hhmm_to_min)
    tt = pd.to_numeric(df.reported_travel_time, errors="coerce")
    df["travel_min"] = (df.arr_min - df.dep_min)
    # fix midnight wrap / bad using reported travel time
    bad = ~(df.travel_min.between(0, 600))
    df.loc[bad, "travel_min"] = tt[bad].where(tt[bad].between(0, 600))
    df["distance"] = pd.to_numeric(df.distance, errors="coerce")

    # GEOID = 5-digit state+county FIPS + 6-digit zero-padded tract code.
    # County codes that aren't 5-digit MD-style (e.g. '-9', '-1-1', out-of-state) -> NA.
    def geoid(county, tract):
        c = county.where(county.str.fullmatch(r"\d{5}"))
        t = tract.where(tract.str.fullmatch(r"\d{1,6}")).str.zfill(6)
        g = c + t
        return g.where(c.notna() & t.notna())

    # ---- HH table ----
    hh = df.drop_duplicates("household_id")[hh_cols].copy()
    hh["home_county"] = hh.home_state_county_fips.where(
        hh.home_state_county_fips.str.fullmatch(r"\d{5}"))
    hh["home_tract"] = geoid(hh.home_state_county_fips, hh.home_tract_fips)
    n_all = len(hh)
    # Restrict to MARYLAND residents (state FIPS 24). The survey covers the
    # tri-state MWCOG region (MD/DC/VA/WV); only MD households are relevant to an
    # MD EV study and match the MD tract centroids at 100%.
    hh = hh[hh.home_county.str.startswith("24", na=False)]
    log("md_filter", all_hh=n_all, md_hh=len(hh))
    n0 = len(hh)
    # impute income by county mode; drop tiny -9 in home_type/ownership
    inc_bad = hh.hh_income_detailed == SENTINEL
    cty_mode = (hh[hh.hh_income_detailed != SENTINEL]
                .groupby("home_county").hh_income_detailed
                .agg(lambda s: s.mode().iat[0] if len(s.mode()) else np.nan))
    hh.loc[inc_bad, "hh_income_detailed"] = hh.loc[inc_bad, "home_county"].map(cty_mode)
    hh["hh_income_detailed"] = hh.hh_income_detailed.fillna(hh.hh_income_detailed.median()).round().astype(int)
    hh = hh[(hh.home_type != SENTINEL) & (hh.home_ownership != SENTINEL)]
    for c in ["hhsize", "numworkers", "numvehicle", "numbicycle"]:
        hh[c] = pd.to_numeric(hh[c], errors="coerce").clip(lower=0)
    hh = hh.dropna(subset=["hhsize", "numworkers", "numvehicle", "numbicycle"])
    # join home centroid
    cen = pd.read_parquet(GEO)
    hh = hh.merge(cen.rename(columns={"tract_geoid": "home_tract", "x": "home_x", "y": "home_y"})
                  [["home_tract", "home_x", "home_y"]], on="home_tract", how="left")
    hh = hh.dropna(subset=["home_x", "home_y"])
    log("hh_clean", kept=len(hh), dropped=n0 - len(hh),
        income_imputed=int(inc_bad.sum()))

    # ---- Person table ----
    per = df.drop_duplicates("person_id")[per_cols].copy()
    n0 = len(per)
    per["age"] = pd.to_numeric(per.age, errors="coerce")
    per = per[(per.age != SENTINEL) & (per.gender != SENTINEL) & per.age.notna()]
    # employment_status is an "Age 16+" question — under-16 are structurally N/A, so give
    # them their OWN category (8 = child/NA) rather than imputing an adult value, which
    # was coding children as "Worker"/"Student" and blurring the child signature. Only
    # the remaining 16+ sentinels are imputed by (age-decade) mode.
    per["age_dec"] = (per.age // 10).clip(0, 9)
    CHILD_EMP = 8
    per.loc[per.age < 16, "employment_status"] = CHILD_EMP
    emp_bad = (per.employment_status == SENTINEL) & (per.age >= 16)
    emp_mode = (per[~emp_bad & (per.employment_status != CHILD_EMP)].groupby("age_dec").employment_status
                .agg(lambda s: s.mode().iat[0] if len(s.mode()) else 0))
    per.loc[emp_bad, "employment_status"] = per.loc[emp_bad, "age_dec"].map(emp_mode).fillna(0)
    lic_bad = per.license == SENTINEL
    lic_mode = (per[~lic_bad].groupby("age_dec").license
                .agg(lambda s: s.mode().iat[0] if len(s.mode()) else 1))
    per.loc[lic_bad, "license"] = per.loc[lic_bad, "age_dec"].map(lic_mode).fillna(1)
    # derived Cirillo person covariates. home_office = ACTUALLY telecommutes (>=1 day/wk);
    # j1_telecommute==1 only means the employer OFFERS the option, which over-counted
    # home_office 2.2x (21.7%->10.0%) and distorted the (beta=0.783) EV-ownership split.
    tcd = pd.to_numeric(per.j1_telecommute_days, errors="coerce").fillna(0)
    per["home_office"] = (tcd > 0).astype(int)
    per["charge_at_work"] = (per.j1_benefits_ev_charging == 1).astype(int)
    per = per[per.household_id.isin(hh.household_id)]
    log("person_clean", kept=len(per), dropped=n0 - len(per),
        emp_imputed=int(emp_bad.sum()), license_imputed=int(lic_bad.sum()))

    # ---- Trip table + feasibility ----
    tr = df[df.person_id.isin(per.person_id)].copy()
    n0_tr, n0_p = len(tr), tr.person_id.nunique()
    tr = tr[(tr.d_activity != SENTINEL) & (tr.travel_mode != SENTINEL)]
    tr = tr[(tr.distance > 0) & (tr.distance <= 200)]
    tr = tr.dropna(subset=["dep_min", "arr_min", "travel_min"])
    tr = tr.sort_values(["person_id", "tripno"]).reset_index(drop=True)
    # dwell = next dep - this arr (within person); last trip -> rest of day
    tr["next_dep"] = tr.groupby("person_id").dep_min.shift(-1)
    tr["dwell_min"] = (tr.next_dep - tr.arr_min)
    last = tr.next_dep.isna()
    tr.loc[last, "dwell_min"] = (24 * 60 - tr.loc[last, "arr_min"]).clip(lower=0)
    tr["dwell_min"] = tr.dwell_min.clip(lower=0)

    # per-person feasibility
    g = tr.groupby("person_id")
    first_o = g.o_activity.first()
    last_d = g.d_activity.last()
    dep_mono = g.apply(lambda x: x.dep_min.is_monotonic_increasing, include_groups=False)
    budget = g.apply(lambda x: (x.travel_min.sum() + x.dwell_min[:-1].sum()) <= 24 * 60,
                     include_groups=False)
    nomiss = ~g.d_activity.apply(lambda s: (s == SENTINEL).any())
    ok = (first_o == HOME) & (last_d == HOME) & dep_mono & budget & nomiss
    keep_ids = ok[ok].index
    tr = tr[tr.person_id.isin(keep_ids)].copy()
    tr["d_county"] = tr.d_state_county_fips.where(tr.d_state_county_fips.str.fullmatch(r"\d{5}"))
    tr["d_tract"] = geoid(tr.d_state_county_fips, tr.d_tract_fips)
    log("trip_feasibility", trip_persons_before=n0_p, feasible_trip_persons=len(keep_ids),
        trips_kept=len(tr), fail_start_home=int((first_o != HOME).sum()),
        fail_end_home=int((last_d != HOME).sum()),
        fail_temporal=int((~dep_mono).sum()), fail_budget=int((~budget).sum()))

    # Population = ALL clean MD persons (non-travelers + feasible travelers kept).
    # Only the TRIP table is feasibility-filtered. n_trips = feasible chain length
    # (0 = non-traveler or a survey day we can't use as a home-anchored chain).
    n_trips = tr.groupby("person_id").size()
    per["n_trips"] = per.person_id.map(n_trips).fillna(0).astype(int)
    log("population", md_persons=len(per), travelers=int((per.n_trips > 0).sum()),
        non_travelers=int((per.n_trips == 0).sum()))
    # chain length distribution (feasible travelers only)
    clen = tr.groupby("person_id").size()
    manifest["chain_length"] = {"mean": round(clen.mean(), 2), "p50": int(clen.median()),
                                "p90": int(clen.quantile(.9)), "p99": int(clen.quantile(.99)),
                                "max": int(clen.max())}

    # ---- train/val/test/holdout split — GROUPED BY HOUSEHOLD (no person/trip
    # leakage across splits), STRATIFIED BY COUNTY. 70/15/10/5. ----
    srng = np.random.default_rng(4711)
    split_of = {}
    for cty, g in hh.groupby("home_county"):
        ids = srng.permutation(g.household_id.to_numpy())
        n = len(ids); c = np.array([.70, .85, .95]) * n
        for i, hid in enumerate(ids):
            split_of[hid] = ("train" if i < c[0] else "val" if i < c[1]
                             else "test" if i < c[2] else "holdout")
    hh["split"] = hh.household_id.map(split_of)
    per["split"] = per.household_id.map(split_of)
    tr["split"] = tr.household_id.map(split_of)
    manifest["split_counts"] = {k: int(v) for k, v in hh.split.value_counts().items()}
    log("split", **manifest["split_counts"])

    # ---- write ----
    keep_hh = ["household_id", "hhsize", "numworkers", "numvehicle", "numbicycle",
               "home_type", "home_ownership", "hh_income_detailed",
               "home_tract", "home_county", "home_x", "home_y", "wthhfin", "split"]
    keep_per = ["household_id", "person_id", "age", "gender", "license",
                "employment_status", "home_office", "charge_at_work", "n_trips",
                "wtperfin", "split"]
    keep_tr = ["household_id", "person_id", "tripno", "o_activity", "d_activity",
               "travel_mode", "distance", "dep_min", "arr_min", "travel_min",
               "dwell_min", "d_tract", "d_county", "wttrdfin", "split"]
    hh[keep_hh].to_parquet(OUT / "survey_hh.parquet", index=False)
    per[keep_per].to_parquet(OUT / "survey_person.parquet", index=False)
    tr[keep_tr].to_parquet(OUT / "survey_trip.parquet", index=False)
    manifest["final"] = {"hh": len(hh), "persons": len(per), "trips": len(tr)}
    (OUT / "cleaning_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("\n=== FINAL ===")
    print(f"households {len(hh):,} | persons {len(per):,} | trips {len(tr):,}")
    print(f"chain length: {manifest['chain_length']}")
    print(f"wrote survey_{{hh,person,trip}}.parquet + cleaning_manifest.json to {OUT}")


if __name__ == "__main__":
    main()
