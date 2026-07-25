#!/usr/bin/env python3
"""
04_ev_ownership_cirillo.py — Lavan-Cirillo EV ownership, calibrated to MD MVA.

Applies the published binomial-logit (Burra & Cirillo 2024, Table 2 Model 2;
Maryland-estimated) per candidate (licensed adult), then bisection-calibrates a
per-county additive constant delta_c so the expected number of owners matches the
Jan-2026 MVA county EV registrations. Samples owners; assigns BEV/PHEV by county
MVA share. Output ev_owners.parquet (~148k EV agents).
"""
from __future__ import annotations
import glob
from pathlib import Path
import re
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
INTERIM = ROOT / "pipeline/data/interim"
DEVICE_SEED = 4711

# Burra & Cirillo (2024) Table 2, Model 2 (verified against docs/ paper). Level-2 ports
# within 1000 m and DCFC ports within 5 mi of the tract centroid; Model 2 replaces
# Model 1's single "public ports" term (0.002) with these two — do NOT include public_5mi.
BETA = dict(income=0.305, single_family=0.479, numbicycle=0.136, numworkers=-0.269,
            transit_trips=-0.044, auto_distance=-0.004, home_office=0.783,
            charge_at_work=0.799, L2_1km=0.011, DCFC_5mi=0.032)
CONST = -7.676

MD = {"ALLEGANY": "24001", "ANNE ARUNDEL": "24003", "BALTIMORE": "24005",
      "CALVERT": "24009", "CAROLINE": "24011", "CARROLL": "24013", "CECIL": "24015",
      "CHARLES": "24017", "DORCHESTER": "24019", "FREDERICK": "24021",
      "GARRETT": "24023", "HARFORD": "24025", "HOWARD": "24027", "KENT": "24029",
      "MONTGOMERY": "24031", "PRINCE GEORGES": "24033", "PRINCE GEORGE'S": "24033",
      "QUEEN ANNES": "24035", "QUEEN ANNE'S": "24035", "SAINT MARYS": "24037",
      "ST. MARY'S": "24037", "SOMERSET": "24039", "TALBOT": "24041",
      "WASHINGTON": "24043", "WICOMICO": "24045", "WORCESTER": "24047",
      "BALTIMORE CITY": "24510"}


def load_mva():
    d = pd.read_csv(glob.glob(str(ROOT / "pipeline/data/reference/mva/MDOT_MVA*.csv"))[0])
    d.columns = [c.strip() for c in d.columns]
    m = d[d.Year_Month == "2026/01"].copy()
    m["Count"] = pd.to_numeric(m.Count.astype(str).str.replace(",", ""), errors="coerce")
    m["fips"] = m.County.astype(str).str.upper().str.strip().map(MD)
    m = m.dropna(subset=["fips"])
    bev = m[m.Fuel_Category == "Electric"].groupby("fips").Count.sum()
    phev = m[m.Fuel_Category == "Plug-In Hybrid"].groupby("fips").Count.sum()
    tot = (bev.add(phev, fill_value=0))
    return tot.to_dict(), (bev / tot).to_dict()   # total EVs, BEV share, per county


def afdc_tract_charging():
    """Port-weighted L2 (<=1000 m) and DCFC (<=5 mi) counts per TRACT CENTROID from the
    AFDC Mar-2026 Maryland public-station snapshot — the paper's exact charging measure
    (Burra & Cirillo count ports within a radius of the census-tract centroid). 2026
    infrastructure: ~4x L2 and ~6x DCFC ports vs the paper's 2019 data."""
    import pyproj
    f = glob.glob(str(ROOT / "pipeline/data/reference/afdc/alt_fuel_stations*MD.csv"))[0]
    d = pd.read_csv(f, low_memory=False)
    d = d[(d["Fuel Type Code"] == "ELEC") & (d["Status Code"] == "E")
          & (d["Access Code"] == "public")]
    lat = pd.to_numeric(d["Latitude"], errors="coerce").to_numpy()
    lon = pd.to_numeric(d["Longitude"], errors="coerce").to_numpy()
    l2 = pd.to_numeric(d["EV Level2 EVSE Num"], errors="coerce").fillna(0).to_numpy()
    dc = pd.to_numeric(d["EV DC Fast Count"], errors="coerce").fillna(0).to_numpy()
    ok = np.isfinite(lat) & np.isfinite(lon)
    tr = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:26985", always_xy=True)
    x, y = tr.transform(lon[ok], lat[ok])
    xy = np.column_stack([x, y]); l2, dc = l2[ok], dc[ok]
    tc = pd.read_parquet(ROOT / "pipeline/data/geo/tract_centroids.parquet")
    txy = tc[["x", "y"]].to_numpy()
    l2m, dcm = l2 > 0, dc > 0
    l2tree, dctree = cKDTree(xy[l2m]), cKDTree(xy[dcm])
    l2p, dcp = l2[l2m], dc[dcm]
    tc["L2_1km"] = [l2p[l2tree.query_ball_point(p, 1000.0)].sum() for p in txy]
    tc["DCFC_5mi"] = [dcp[dctree.query_ball_point(p, 8046.7)].sum() for p in txy]
    print(f"[afdc] {len(xy):,} public stations; ports L2 {int(l2.sum()):,} / DCFC {int(dc.sum()):,}; "
          f"per-tract mean L2 {tc.L2_1km.mean():.1f}, DCFC {tc.DCFC_5mi.mean():.1f}")
    tc["tract_geoid"] = tc.tract_geoid.astype(str)
    tc[["tract_geoid", "L2_1km", "DCFC_5mi"]].to_parquet(INTERIM / "tract_charging.parquet", index=False)
    return tc.set_index("tract_geoid")[["L2_1km", "DCFC_5mi"]]


def main():
    rng = np.random.default_rng(DEVICE_SEED)
    pop = pd.read_parquet(INTERIM / "synth_person.parquet")
    for c in ["hh_income_detailed", "numbicycle", "numworkers", "home_type",
              "home_office", "charge_at_work", "license", "age"]:
        pop[c] = pd.to_numeric(pop[c], errors="coerce")
    cand = pop[(pop.age >= 16) & (pop.license == 1) & pop.home_county.isin(set(MD.values()))].copy()
    print(f"[candidates] {len(cand):,} licensed adults in MD")

    # covariates
    cand["income"] = cand.hh_income_detailed
    cand["single_family"] = cand.home_type.isin([1, 2]).astype(float)
    # transit_trips / auto_distance: survey cell means by (county, income) [minor coeffs]
    sp = pd.read_parquet(INTERIM / "survey_person.parquet")
    st = pd.read_parquet(INTERIM / "survey_trip.parquet")
    hh = pd.read_parquet(INTERIM / "survey_hh.parquet")[["household_id", "home_county", "hh_income_detailed"]]
    auto = st[st.travel_mode == 4].groupby("person_id").distance.sum()
    trans = st[st.travel_mode.isin([7, 8, 9, 10])].groupby("person_id").size()
    sp2 = sp.merge(hh, on="household_id")
    sp2["auto"] = sp2.person_id.map(auto).fillna(0); sp2["trans"] = sp2.person_id.map(trans).fillna(0)
    cell = sp2.groupby(["home_county", "hh_income_detailed"]).agg(auto=("auto", "mean"), trans=("trans", "mean"))
    key = list(zip(cand.home_county, cand.income))
    cand["auto_distance"] = pd.Series([cell.auto.get(k, sp2.auto.mean()) for k in key], index=cand.index)
    cand["transit_trips"] = pd.Series([cell.trans.get(k, sp2.trans.mean()) for k in key], index=cand.index)
    # charger counts (AFDC 2026, per tract centroid -> joined to candidates by home tract)
    tch = afdc_tract_charging()
    cand["home_tract"] = cand.home_tract.astype(str)
    cand = cand.join(tch, on="home_tract")
    cand["L2_1km"] = cand["L2_1km"].fillna(0.0)
    cand["DCFC_5mi"] = cand["DCFC_5mi"].fillna(0.0)

    # drop any candidate with a NaN covariate (OOV categories) — else a single NaN
    # poisons its whole county's calibration sum.
    n0 = len(cand)
    cand = cand.dropna(subset=list(BETA)).reset_index(drop=True)
    print(f"[covariates] dropped {n0 - len(cand)} candidates with NaN covariate; {len(cand):,} clean")

    # utility (without constant/delta)
    xb = sum(BETA[k] * cand[k].to_numpy() for k in BETA)
    mva_tot, mva_bev = load_mva()

    # calibrate delta_c per county so sum(expit(xb+const+delta)) == MVA count
    def expit(z): return 1.0 / (1.0 + np.exp(-z))
    cand["p"] = 0.0
    owners = []
    print("[calibrate] per-county delta_c -> MVA target")
    for fips, sub in cand.groupby("home_county"):
        target = mva_tot.get(fips, 0)
        z0 = xb[sub.index.map(cand.index.get_loc)] if False else (CONST + sum(BETA[k]*sub[k].to_numpy() for k in BETA))
        lo, hi = -20.0, 20.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if expit(z0 + mid).sum() < target:
                lo = mid
            else:
                hi = mid
        delta = (lo + hi) / 2
        p = expit(z0 + delta)
        pick = rng.random(len(sub)) < p
        o = sub[pick].copy()
        o["ev_powertrain"] = np.where(rng.random(len(o)) < mva_bev.get(fips, 0.738), "BEV", "PHEV")
        owners.append(o)
    ev = pd.concat(owners, ignore_index=True)
    ev.to_parquet(INTERIM / "ev_owners.parquet", index=False)

    print(f"\n[owners] {len(ev):,} EV agents (MVA target {int(sum(mva_tot.values())):,})")
    print(f"  BEV {(ev.ev_powertrain=='BEV').mean():.3f} (MVA ~0.738)")
    got = ev.groupby("home_county").size(); tgt = pd.Series(mva_tot)
    corr = pd.concat([got.rename("got"), tgt.rename("tgt")], axis=1).dropna().corr().iloc[0, 1]
    print(f"  county count corr vs MVA: {corr:.4f}")
    print(f"  ownership by income decile (gradient check):")
    print((ev.groupby("income").size() / cand.groupby("income").size()).round(4).to_string())


if __name__ == "__main__":
    main()
