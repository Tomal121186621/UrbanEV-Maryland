#!/usr/bin/env python3
"""
06_build_plans.py — vehicle attributes + POI geolocation -> MATSim plans for 2026 EV owners.

For every EV owner (ev_owners.parquet) this:
  1. assigns a vehicle (type/battery/consumption sampled from the MD EV fleet shares),
  2. assigns HOME + WORK charging with an empirically-grounded rule:
       - home-charger probability by dwelling type x tenure x income (EV-owner literature:
         single-family ~84-94%, apartment <50%, lower for renters/low-income), then
         rescaled PER COUNTY so the county mean matches the NREL submission-278
         home-charging-access share at the 2026 MD penetration (~6.3% -> ~0.96);
       - L1/L2 power among home chargers ~88% L2 / 12% L1 (EPRI 2024 EV Driver Survey),
         L1 likelier for low-income / multifamily;
       - workplace charger from the survey `charge_at_work` flag (L2 = 7.2 kW),
  3. per-agent betaMoney = -1.0*(125000/income_mid)^0.5 and value-of-time (income-scaled),
     one fixed range-anxiety threshold for all, initial SOC, smart-charging awareness,
  4. generates the person's activity day with the discretized trip CVAE and places each
     activity at a type-matched OSM POI at ~the generated trip distance (home = home xy),
  5. writes plans_maryland_ev_2026.xml.gz (ALL demographics on every agent) +
     electric_vehicles.xml.

Usage: python 06_build_plans.py [--n N] [--days D]   (--n: smoke-test subset; --days: tiling)
"""
from __future__ import annotations
import sys, gzip, glob, json, argparse
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from scipy.spatial import cKDTree
from scipy.stats import beta as scipy_beta

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec
from src.cvae import MixedCVAE
from src import tripdisc
from src.trips import COND_CAT, COND_NUM
from src.twostage import person_cond

INTERIM = ROOT / "pipeline/data/interim"
REF = ROOT / "pipeline/data/reference"
CK = ROOT / "pipeline/checkpoints"
OUT = ROOT / "pipeline/output/plans"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 6061

# ---- attribute constants (Burra-Cirillo proposal §3-4 + charger research) -----
INCOME_MID = {1: 7500., 2: 20000., 3: 30000., 4: 42500., 5: 62500., 6: 87500.,
              7: 125000., 8: 200000.}
DEFAULT_INCOME = 60000.
L1_KW, L2_KW = 1.4, 7.2
TAU_ALL = 0.20                       # single range-anxiety threshold for all agents
DETOUR = 1.30                        # beeline->network detour: place at euclid=dist/DETOUR
                                     # so MATSim network routing reproduces the trip distance
ACTIVITY = {1: "home", 2: "work", 3: "volunteer", 4: "school", 5: "shopping",
            6: "meal_quick", 7: "meal", 8: "gas", 9: "healthcare", 10: "errand",
            11: "socialize", 12: "civic_religious", 13: "exercise", 14: "recreation",
            15: "entertainment", 16: "dropoff_pickup", 17: "other", 18: "other"}
TESLA = {"model_s", "model_3", "model_x", "model_y", "cybertruck"}
MD = {"ALLEGANY": "24001", "ANNE ARUNDEL": "24003", "BALTIMORE": "24005", "CALVERT": "24009",
      "CAROLINE": "24011", "CARROLL": "24013", "CECIL": "24015", "CHARLES": "24017",
      "DORCHESTER": "24019", "FREDERICK": "24021", "GARRETT": "24023", "HARFORD": "24025",
      "HOWARD": "24027", "KENT": "24029", "MONTGOMERY": "24031", "PRINCE GEORGES": "24033",
      "PRINCE GEORGE'S": "24033", "QUEEN ANNES": "24035", "QUEEN ANNE'S": "24035",
      "SAINT MARYS": "24037", "ST. MARY'S": "24037", "SOMERSET": "24039", "TALBOT": "24041",
      "WASHINGTON": "24043", "WICOMICO": "24045", "WORCESTER": "24047", "BALTIMORE CITY": "24510"}

# home-charger base probability by (home_type, ownership 1=own/2=rent) — EV-owner literature
HOME_P = {(1, 1): 0.94, (1, 2): 0.62, (2, 1): 0.90, (2, 2): 0.58,
          (3, 1): 0.50, (3, 2): 0.35, (4, 1): 0.72, (4, 2): 0.55,
          (5, 1): 0.40, (5, 2): 0.35}
INC_MULT = {1: 0.80, 2: 0.83, 3: 0.87, 4: 0.92, 5: 0.97, 6: 1.0, 7: 1.03, 8: 1.05}
EV_PEN_2026 = 0.063                  # 148k EVs / ~2.34M passenger vehicles


def nrel278_access():
    """Per-county home-charging access at the 2026 penetration (interp of NREL-278 cols)."""
    d = pd.read_csv(REF / "nrel278/nrel278_md_access_by_county.csv")
    lv = [0.02, 0.04, 0.10, 0.20, 0.50]
    acc = {}
    for _, r in d.iterrows():
        fp = MD.get(str(r.county_name).split(",")[0].strip().upper())
        if fp:
            acc[fp] = float(np.interp(EV_PEN_2026, lv, [r[str(c)] for c in lv]))
    return acc


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def hms(minutes):
    s = int(round(max(0.0, minutes) * 60))
    return f"{s//3600:02d}:{s//60%60:02d}:{s%60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    ev = pd.read_parquet(INTERIM / "ev_owners.parquet")
    if args.n:
        ev = ev.sample(args.n, random_state=SEED).reset_index(drop=True)
    for c in ["home_type", "home_ownership", "hh_income_detailed", "employment_status",
              "charge_at_work", "hhsize", "numworkers", "numvehicle", "numbicycle",
              "gender", "license", "age", "home_office"]:
        ev[c] = pd.to_numeric(ev[c], errors="coerce")
    ev["fips"] = ev.home_county.astype(float).astype(int).astype(str).str.zfill(5)
    N = len(ev)
    print(f"[plans] {N:,} EV owners | device {DEV} | days={args.days}")

    # ---- vehicle assignment (sample type by fleet share within powertrain) -----
    look = pd.read_csv(REF / "vehicles/ev_counterfactual_mpg_lookup.csv")
    look["powertrain"] = look.powertrain.str.upper()
    veh = {}
    for pt in ["BEV", "PHEV"]:
        sub = look[look.powertrain == pt]
        veh[pt] = (sub.ev_type.to_numpy(),
                   (sub.fleet_share_pct / sub.fleet_share_pct.sum()).to_numpy(),
                   dict(zip(sub.ev_type, sub.battery_kwh)))
    ev_type = np.empty(N, object); battery = np.zeros(N)
    for pt in ["BEV", "PHEV"]:
        m = (ev.ev_powertrain == pt).to_numpy()
        types, probs, batt = veh[pt]
        pick = rng.choice(len(types), m.sum(), p=probs)
        ev_type[m] = types[pick]; battery[m] = [batt[types[i]] for i in pick]
    ev["ev_type"] = ev_type; ev["battery"] = battery

    # ---- home / work charger assignment ---------------------------------------
    base = np.array([HOME_P.get((int(h), int(o)), 0.6) * INC_MULT.get(int(i), 1.0)
                     for h, o, i in zip(ev.home_type.fillna(1), ev.home_ownership.fillna(1),
                                        ev.hh_income_detailed.fillna(6))])
    base = np.clip(base, 0.05, 0.98)
    acc = nrel278_access()
    p_home = base.copy()
    for fp, sub in ev.groupby("fips"):        # rescale each county mean -> NREL-278 target
        idx = sub.index.to_numpy()
        tgt = acc.get(fp, 0.96); cur = base[idx].mean()
        if cur > 0:
            p_home[idx] = np.clip(base[idx] * (tgt / cur), 0.02, 0.99)
    has_home = rng.random(N) < p_home
    # L1/L2 among home chargers (~88% L2; L1 likelier for low-income / multifamily)
    p_l2 = np.where(ev.hh_income_detailed.fillna(6) <= 3, 0.73, 0.88)
    p_l2 = np.where(ev.home_type.fillna(1) >= 3, p_l2 - 0.10, p_l2)
    home_kw = np.where(has_home, np.where(rng.random(N) < np.clip(p_l2, 0.5, 0.95), L2_KW, L1_KW), 0.0)
    work_kw = np.where(ev.charge_at_work.fillna(0) == 1, L2_KW, 0.0)
    print(f"[charger] home access {has_home.mean():.3f} (L2 among them "
          f"{(home_kw[has_home] == L2_KW).mean():.2f}); work access {(work_kw > 0).mean():.3f}")

    # ---- economic + behavioural attributes ------------------------------------
    inc_mid = ev.hh_income_detailed.map(INCOME_MID).fillna(DEFAULT_INCOME).to_numpy()
    beta_money = -1.0 * (125000.0 / np.maximum(inc_mid, 1)) ** 0.5
    vot = inc_mid / 2080.0 * 0.50 * np.where(ev.employment_status.fillna(0) == 0, 1.0, 0.60)
    is_bev = (ev.ev_powertrain == "BEV").to_numpy()
    soc_frac = np.where(is_bev, np.clip(scipy_beta.rvs(4, 2, size=N, random_state=rng), 0.20, 0.95),
                        rng.uniform(0.30, 0.90, N))
    p_smart = np.clip(0.30 + 0.20 * (inc_mid >= 100000) + 0.10 * (ev.age.fillna(50) < 45), 0, 0.85)
    smart = rng.random(N) < p_smart
    util_factor = np.where(is_bev, 1.0, 0.58)
    charger_types = [("L1,L2,DCFC,DCFC_TESLA" if (t in TESLA) else "L1,L2,DCFC") for t in ev_type]

    # ---- POI spatial index per activity type ----------------------------------
    poi = pd.read_parquet(ROOT / "pipeline/data/osm/pois.parquet")
    trees = {int(a): (cKDTree(g[["x", "y"]].to_numpy()), g[["x", "y"]].to_numpy())
             for a, g in poi.groupby("act")}
    all_pts = poi[["x", "y"]].to_numpy(); any_tree = (cKDTree(all_pts), all_pts)
    XLO, YLO = all_pts.min(0); XHI, YHI = all_pts.max(0)   # Maryland bounding box (from POIs)

    def place(prev, act, dist_m, r):
        # Place at EXACTLY the generated trip distance (VMT faithful) in the DIRECTION of a
        # real POI of the activity type (realistic, land-use-consistent bearing — usually
        # inland toward populated areas). Try the POIs whose own distance is closest to the
        # target first, and keep the first bearing that lands inside Maryland.
        tree, pts = trees.get(act, any_tree)
        _, ii = tree.query(prev, k=min(60, len(pts)))
        ii = np.atleast_1d(ii)
        order = ii[np.argsort(np.abs(np.linalg.norm(pts[ii] - prev, axis=1) - dist_m))]
        cand0 = None
        for idx in order[:25]:
            v = pts[idx] - prev; nv = np.hypot(*v)
            if nv < 1:
                continue
            c = prev + v / nv * dist_m
            if cand0 is None:
                cand0 = c
            if XLO <= c[0] <= XHI and YLO <= c[1] <= YHI:
                return c
        return cand0 if cand0 is not None else prev

    # ---- trip model ------------------------------------------------------------
    tck = torch.load(CK / "trip_disc_cvae.pt", map_location=DEV, weights_only=False)
    tm = MixedCVAE(tck["cat_cards"], tck["num_fields"], tck["latent"], tck["hidden"],
                   tck["cond_dim"], dropout=tck.get("dropout", 0.0)).to(DEV).eval()
    tm.load_state_dict(tck["state_dict"])
    tcodec = DataCodec.load(CK / "trip_disc_codec.json"); ccodec = DataCodec.load(CK / "cond_codec.json")
    edges = json.load(open(CK / "mag_edges.json"))

    def pad_idx(f, v): c = tcodec.cats.get(f, []); return [c.index(v)] if v in c else []
    forbid = {}
    for j in range(tripdisc.K_MAX):
        forbid[f"mode_{j}"] = pad_idx(f"mode_{j}", "0"); forbid[f"act_{j}"] = pad_idx(f"act_{j}", "0")
        forbid[f"depb_{j}"] = pad_idx(f"depb_{j}", "-1")
        for mg in ("logdistb", "travelb"):
            forbid[f"{mg}_{j}"] = pad_idx(f"{mg}_{j}", "-1")

    # ---- write outputs (stream) ------------------------------------------------
    pf = gzip.open(OUT / "plans_maryland_ev_2026.xml.gz", "wt")
    vf = open(OUT / "electric_vehicles.xml", "w")
    pf.write('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n'
             '<population>\n')
    vf.write('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<!DOCTYPE vehicles SYSTEM "http://matsim.org/files/dtd/electric_vehicles_v1.dtd">\n'
             '<vehicles>\n')

    def A(name, cls, val):
        return f'      <attribute name="{name}" class="java.lang.{cls}">{esc(val)}</attribute>\n'

    DEMOG = ["home_county", "home_type", "home_ownership", "hh_income_detailed", "hhsize",
             "numworkers", "numvehicle", "numbicycle", "gender", "license",
             "employment_status", "home_office", "charge_at_work", "age"]
    B = 20000; ntrips = 0
    ev_reset = ev.reset_index(drop=True)
    for b0 in range(0, N, B):
        bl = ev_reset.iloc[b0:b0 + B]
        cond = person_cond(bl, ccodec, DEV)
        s = tm.sample(len(bl), cond=cond, device=DEV, forbid=forbid)
        dec = {f: tcodec.decode_cat(f, s[f]) for f in tripdisc.SLOT_CAT}
        for k in range(len(bl)):
            g = b0 + k; row = ev_reset.iloc[g]
            pid = str(row.person_id); hx, hy = float(row.home_x), float(row.home_y)
            r = np.random.default_rng(SEED + g)
            chain = tripdisc.repair_disc(dec, k, edges, r)
            # geolocate
            coords, prev = [], np.array([hx, hy]); labels = []
            for t in chain:
                act = int(t["activity"]); labels.append(ACTIVITY.get(act, "other"))
                xy = np.array([hx, hy]) if act == 1 else place(prev, act, t["distance"] * 1609.344 / DETOUR, r)
                coords.append(xy); prev = xy
            # person
            pf.write(f'  <person id="{esc(pid)}">\n    <attributes>\n')
            pf.write(A("income", "Double", f"{inc_mid[g]:.1f}"))
            for c in DEMOG:
                v = row[c]; v = "" if pd.isna(v) else (int(v) if float(v) == int(float(v)) else v)
                pf.write(A(c, "Integer" if isinstance(v, int) else "String", v))
            pf.write(A("evType", "String", row.ev_powertrain))
            pf.write(A("evModel", "String", row.ev_type))
            pf.write(A("homeChargerPower", "Double", f"{home_kw[g]:.1f}"))
            pf.write(A("workChargerPower", "Double", f"{work_kw[g]:.1f}"))
            pf.write(A("betaMoney", "Double", f"{beta_money[g]:.4f}"))
            pf.write(A("valueOfTime", "Double", f"{vot[g]:.4f}"))
            pf.write(A("rangeAnxietyThreshold", "Double", f"{TAU_ALL:.2f}"))
            pf.write(A("smartChargingAware", "Boolean", "true" if smart[g] else "false"))
            pf.write(A("utilityFactor", "Double", f"{util_factor[g]:.2f}"))
            pf.write('    </attributes>\n    <plan selected="yes">\n')
            # continuous act-leg-act sequence: one initial home, then day-tiled trips; the
            # end-of-day home (last chain activity) flows into the next day's first leg
            # (its end_time = next day's first departure) — no duplicated home, legs=acts-1.
            dep0 = chain[0]["dep_min"] if chain else 480.0
            pf.write(f'      <activity type="home" x="{hx:.2f}" y="{hy:.2f}" '
                     f'end_time="{hms(dep0)}" />\n')
            nleg = len(chain)
            for day in range(args.days):
                off = day * 1440.0
                for j, (t, xy, lab) in enumerate(zip(chain, coords, labels)):
                    pf.write(f'      <leg mode="car" trav_time="{hms(t["arr_min"] - t["dep_min"])}" />\n')
                    if (day == args.days - 1) and (j == nleg - 1):
                        et = ""                                            # final activity: open-ended
                    elif j == nleg - 1:                                    # end-of-day home
                        et = f' end_time="{hms((day + 1) * 1440.0 + dep0)}"'
                    else:
                        et = f' end_time="{hms(off + t["arr_min"] + t["dwell_min"])}"'
                    pf.write(f'      <activity type="{lab}" x="{xy[0]:.2f}" y="{xy[1]:.2f}" '
                             f'start_time="{hms(off + t["arr_min"])}"{et} />\n')
                ntrips += nleg
            pf.write('    </plan>\n  </person>\n')
            # vehicle
            vf.write(f'  <vehicle id="{esc(pid)}" battery_capacity="{battery[g]:.2f}" '
                     f'initial_soc="{soc_frac[g] * battery[g]:.2f}" '
                     f'charger_types="{charger_types[g]}" vehicle_type="{esc(row.ev_type)}" />\n')
        print(f"  ...{min(b0 + B, N):,}/{N:,}", flush=True)
    pf.write('</population>\n'); pf.close()
    vf.write('</vehicles>\n'); vf.close()
    print(f"[done] {N:,} agents, {ntrips:,} trip-legs -> {OUT}/plans_maryland_ev_2026.xml.gz "
          f"+ electric_vehicles.xml")


if __name__ == "__main__":
    main()
