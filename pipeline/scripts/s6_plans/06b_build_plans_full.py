#!/usr/bin/env python3
"""
06b_build_plans_full.py — FULL-population MATSim plans (non-EV background traffic + EV
agents) for congestion-aware assignment, household-sampled.

Differences vs 06_build_plans.py (EV-only):
  * population = ALL synthetic persons in a household-grouped sample (default 25%),
    not just EV owners — non-EV drivers provide real congestion.
  * non-EV agents: trip-CVAE chains with survey modes mapped to MATSim modes
    (4/3 -> car network; 5 -> ride; 1 -> walk; 2 -> bike; transit -> pt); persons with
    no car-driver leg (or no license / age<16) are skipped as network-irrelevant.
  * EV agents keep the all-car convention of the validated EV-only pipeline (the EV is
    the household's tracked vehicle; SOC continuity requires it drives all legs).
  * subpopulation attribute ("ev"/"nonev") for strategy separation in the config.
  * NEW EV attributes: phevGasCostPerKwh (research/phev_gas_fallback_costs.csv — EPA
    charge-sustaining mpg + AAA MD fuel prices) for the Java gas-fallback scoring;
    charger_types now honor per-model DCFC capability (18/21 PHEV archetypes are
    L2-only per urbanev_vehicletypes.xml — they no longer get DCFC permission).

Outputs: plans_maryland_full_2026_<pct>.xml.gz + electric_vehicles_full_<pct>.xml
Usage: python 06b_build_plans_full.py [--sample 0.25] [--days 3] [--n N(smoke, persons)]
"""
from __future__ import annotations
import sys, gzip, json, argparse, re, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from scipy.stats import beta as scipy_beta

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec
from src.cvae import MixedCVAE
from src import tripdisc
from src.twostage import person_cond

# import the EV-only builder as a module for its constants/helpers (single source of truth)
_spec = importlib.util.spec_from_file_location("bp6", Path(__file__).parent / "06_build_plans.py")
bp6 = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bp6)

INTERIM = ROOT / "pipeline/data/interim"
REF = ROOT / "pipeline/data/reference"
CK = ROOT / "pipeline/checkpoints"
OUT = ROOT / "pipeline/output/plans"
DEV = "cuda" if torch.cuda.is_available() else "cpu"
SEED = bp6.SEED
HH_SEED = 1001                        # household sampling seed (matches prior 25% convention)
MODE_MAP = {4: "car", 3: "car", 5: "ride", 1: "walk", 2: "bike"}   # else -> "pt"


def phev_gas_costs():
    d = pd.read_csv(ROOT / "research/phev_gas_fallback_costs.csv")
    return dict(zip(d.ev_type, d.gas_cost_per_kwh))


def l2_only_types():
    """PHEV archetypes flagged 'L2 only' in the vehicletypes comments (no DCFC port)."""
    s = set()
    for ln in open(ROOT / "Input/vehicles/urbanev_vehicletypes.xml"):
        if "L2 only" in ln:
            m = re.search(r'name="([^"]+)"', ln)
            if m: s.add(m.group(1))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=float, default=0.25)
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--n", type=int, default=0, help="smoke: cap persons AFTER sampling")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"{int(args.sample * 100)}pct"

    # ---- population: household-grouped sample of ALL synth persons -------------
    per = pd.read_parquet(INTERIM / "synth_person.parquet")
    hh_ids = per.synth_hh_id.unique()
    smp_rng = np.random.default_rng(HH_SEED)
    keep_hh = set(smp_rng.choice(hh_ids, size=int(len(hh_ids) * args.sample), replace=False))
    per = per[per.synth_hh_id.isin(keep_hh)].reset_index(drop=True)
    own = pd.read_parquet(INTERIM / "ev_owners.parquet")
    per = per.merge(own[["person_id", "ev_powertrain"]], on="person_id", how="left")
    per["is_ev"] = per.ev_powertrain.notna()
    # drivers only among non-EV (EV owners are drivers by construction)
    per["age"] = pd.to_numeric(per.age, errors="coerce")
    per["license"] = pd.to_numeric(per.license, errors="coerce")
    per = per[per.is_ev | ((per.license == 1) & (per.age >= 16))].reset_index(drop=True)
    if args.n:
        per = per.iloc[:args.n].reset_index(drop=True)
    for c in ["home_type", "home_ownership", "hh_income_detailed", "employment_status",
              "charge_at_work", "hhsize", "numworkers", "numvehicle", "numbicycle",
              "gender", "home_office"]:
        per[c] = pd.to_numeric(per[c], errors="coerce")
    per["fips"] = per.home_county.astype(float).astype(int).astype(str).str.zfill(5)
    N = len(per)
    n_ev = int(per.is_ev.sum())
    print(f"[full-plans] sample {args.sample:.0%} -> {N:,} candidate persons "
          f"({n_ev:,} EV owners) | device {DEV} | days={args.days}")

    # ---- EV vehicle + charger + behavioural attributes (same logic as 06) ------
    look = pd.read_csv(REF / "vehicles/ev_counterfactual_mpg_lookup.csv")
    look["powertrain"] = look.powertrain.str.upper()
    veh = {}
    for pt in ["BEV", "PHEV"]:
        sub = look[look.powertrain == pt]
        veh[pt] = (sub.ev_type.to_numpy(),
                   (sub.fleet_share_pct / sub.fleet_share_pct.sum()).to_numpy(),
                   dict(zip(sub.ev_type, sub.battery_kwh)))
    ev_type = np.array([None] * N, object); battery = np.zeros(N)
    for pt in ["BEV", "PHEV"]:
        m = (per.ev_powertrain == pt).to_numpy()
        types, probs, batt = veh[pt]
        pick = rng.choice(len(types), m.sum(), p=probs)
        ev_type[m] = types[pick]; battery[m] = [batt[types[i]] for i in pick]
    per["ev_type"] = ev_type

    base = np.array([bp6.HOME_P.get((int(h), int(o)), 0.6) * bp6.INC_MULT.get(int(i), 1.0)
                     for h, o, i in zip(per.home_type.fillna(1), per.home_ownership.fillna(1),
                                        per.hh_income_detailed.fillna(6))])
    base = np.clip(base, 0.05, 0.98)
    acc = bp6.nrel278_access()
    p_home = base.copy()
    evm = per.is_ev.to_numpy()
    for fp, sub in per[evm].groupby("fips"):
        idx = sub.index.to_numpy()
        tgt = acc.get(fp, 0.96); cur = base[idx].mean()
        if cur > 0:
            p_home[idx] = np.clip(base[idx] * (tgt / cur), 0.02, 0.99)
    has_home = (rng.random(N) < p_home) & evm
    p_l2 = np.where(per.hh_income_detailed.fillna(6) <= 3, 0.73, 0.88)
    p_l2 = np.where(per.home_type.fillna(1) >= 3, p_l2 - 0.10, p_l2)
    home_kw = np.where(has_home, np.where(rng.random(N) < np.clip(p_l2, 0.5, 0.95),
                                          bp6.L2_KW, bp6.L1_KW), 0.0)
    work_kw = np.where(evm & (per.charge_at_work.fillna(0) == 1), bp6.L2_KW, 0.0)
    if evm.any():
        print(f"[charger] EV home access {has_home[evm].mean():.3f}; "
              f"work access {(work_kw[evm] > 0).mean():.3f}")

    inc_mid = per.hh_income_detailed.map(bp6.INCOME_MID).fillna(bp6.DEFAULT_INCOME).to_numpy()
    beta_money = -1.0 * (125000.0 / np.maximum(inc_mid, 1)) ** 0.5
    vot = inc_mid / 2080.0 * 0.50 * np.where(per.employment_status.fillna(0) == 0, 1.0, 0.60)
    is_bev = (per.ev_powertrain == "BEV").to_numpy()
    soc_frac = np.where(is_bev, np.clip(scipy_beta.rvs(4, 2, size=N, random_state=rng), 0.20, 0.95),
                        rng.uniform(0.30, 0.90, N))
    p_smart = np.clip(0.30 + 0.20 * (inc_mid >= 100000) + 0.10 * (per.age.fillna(50) < 45), 0, 0.85)
    smart = rng.random(N) < p_smart
    util_factor = np.where(is_bev, 1.0, 0.58)
    gas_cost = phev_gas_costs()
    l2only = l2_only_types()
    def ctypes(t, pt):
        if pt == "BEV":
            return "L1,L2,DCFC,DCFC_TESLA" if t in bp6.TESLA else "L1,L2,DCFC"
        return "L1,L2" if t in l2only else "L1,L2,DCFC"

    # ---- POI index + trip model (same as 06) ------------------------------------
    poi = pd.read_parquet(ROOT / "pipeline/data/osm/pois.parquet")
    from scipy.spatial import cKDTree
    trees = {int(a): (cKDTree(g[["x", "y"]].to_numpy()), g[["x", "y"]].to_numpy())
             for a, g in poi.groupby("act")}
    all_pts = poi[["x", "y"]].to_numpy(); any_tree = (cKDTree(all_pts), all_pts)
    XLO, YLO = all_pts.min(0); XHI, YHI = all_pts.max(0)

    def place(prev, act, dist_m, r):
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

    # ---- stream outputs ----------------------------------------------------------
    esc, hms, A_fmt = bp6.esc, bp6.hms, None
    pf = gzip.open(OUT / f"plans_maryland_full_2026_{tag}.xml.gz", "wt")
    vf = open(OUT / f"electric_vehicles_full_{tag}.xml", "w")
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
    B = 20000
    n_written = n_ev_written = n_skipped_nocar = ntrips = 0
    per_reset = per.reset_index(drop=True)
    for b0 in range(0, N, B):
        bl = per_reset.iloc[b0:b0 + B]
        cond = person_cond(bl, ccodec, DEV)
        s = tm.sample(len(bl), cond=cond, device=DEV, forbid=forbid)
        dec = {f: tcodec.decode_cat(f, s[f]) for f in tripdisc.SLOT_CAT}
        for k in range(len(bl)):
            g = b0 + k; row = per_reset.iloc[g]
            is_ev = bool(row.is_ev)
            pid = str(row.person_id); hx, hy = float(row.home_x), float(row.home_y)
            r = np.random.default_rng(SEED + g)
            chain = tripdisc.repair_disc(dec, k, edges, r)
            modes = ([ "car"] * len(chain) if is_ev else
                     [MODE_MAP.get(int(t.get("mode", 4)), "pt") for t in chain])
            if not is_ev and "car" not in modes:
                n_skipped_nocar += 1
                continue
            coords, prev, labels = [], np.array([hx, hy]), []
            for t in chain:
                act = int(t["activity"]); labels.append(bp6.ACTIVITY.get(act, "other"))
                xy = np.array([hx, hy]) if act == 1 else place(prev, act, t["distance"] * 1609.344 / bp6.DETOUR, r)
                coords.append(xy); prev = xy
            pf.write(f'  <person id="{esc(pid)}">\n    <attributes>\n')
            pf.write(A("subpopulation", "String", "ev" if is_ev else "nonev"))
            pf.write(A("income", "Double", f"{inc_mid[g]:.1f}"))
            for c in DEMOG:
                v = row[c]; v = "" if pd.isna(v) else (int(v) if float(v) == int(float(v)) else v)
                pf.write(A(c, "Integer" if isinstance(v, int) else "String", v))
            if is_ev:
                pf.write(A("evType", "String", row.ev_powertrain))
                pf.write(A("evModel", "String", row.ev_type))
                pf.write(A("homeChargerPower", "Double", f"{home_kw[g]:.1f}"))
                pf.write(A("workChargerPower", "Double", f"{work_kw[g]:.1f}"))
                pf.write(A("betaMoney", "Double", f"{beta_money[g]:.4f}"))
                pf.write(A("valueOfTime", "Double", f"{vot[g]:.4f}"))
                pf.write(A("rangeAnxietyThreshold", "Double", f"{bp6.TAU_ALL:.2f}"))
                pf.write(A("smartChargingAware", "Boolean", "true" if smart[g] else "false"))
                pf.write(A("utilityFactor", "Double", f"{util_factor[g]:.2f}"))
                if row.ev_powertrain == "PHEV":
                    gc = gas_cost.get(row.ev_type)
                    if gc is None:
                        raise SystemExit(f"no gas cost for PHEV type {row.ev_type}")
                    pf.write(A("phevGasCostPerKwh", "Double", f"{gc:.4f}"))
            pf.write('    </attributes>\n    <plan selected="yes">\n')
            dep0 = chain[0]["dep_min"] if chain else 480.0
            pf.write(f'      <activity type="home" x="{hx:.2f}" y="{hy:.2f}" '
                     f'end_time="{hms(dep0)}" />\n')
            nleg = len(chain)
            for day in range(args.days):
                off = day * 1440.0
                for j, (t, xy, lab, md) in enumerate(zip(chain, coords, labels, modes)):
                    pf.write(f'      <leg mode="{md}" trav_time="{hms(t["arr_min"] - t["dep_min"])}" />\n')
                    if (day == args.days - 1) and (j == nleg - 1):
                        et = ""
                    elif j == nleg - 1:
                        et = f' end_time="{hms((day + 1) * 1440.0 + dep0)}"'
                    else:
                        et = f' end_time="{hms(off + t["arr_min"] + t["dwell_min"])}"'
                    pf.write(f'      <activity type="{lab}" x="{xy[0]:.2f}" y="{xy[1]:.2f}" '
                             f'start_time="{hms(off + t["arr_min"])}"{et} />\n')
                ntrips += nleg
            pf.write('    </plan>\n  </person>\n')
            n_written += 1
            if is_ev:
                n_ev_written += 1
                vf.write(f'  <vehicle id="{esc(pid)}" battery_capacity="{battery[g]:.2f}" '
                         f'initial_soc="{soc_frac[g] * battery[g]:.2f}" '
                         f'charger_types="{ctypes(row.ev_type, row.ev_powertrain)}" '
                         f'vehicle_type="{esc(row.ev_type)}" />\n')
        print(f"  ...{min(b0 + B, N):,}/{N:,} (written {n_written:,})", flush=True)
    pf.write('</population>\n'); pf.close()
    vf.write('</vehicles>\n'); vf.close()
    print(f"[done] {n_written:,} agents ({n_ev_written:,} EV, "
          f"{n_written - n_ev_written:,} non-EV; {n_skipped_nocar:,} skipped car-less), "
          f"{ntrips:,} trip-legs\n  -> plans_maryland_full_2026_{tag}.xml.gz + "
          f"electric_vehicles_full_{tag}.xml")


if __name__ == "__main__":
    main()
