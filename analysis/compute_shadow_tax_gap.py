#!/usr/bin/env python3
"""
compute_shadow_tax_gap.py — the revenue objective R*.

R* = annual Maryland motor-fuel tax NOT collected because the simulated EV fleet
drives on electricity instead of gasoline. This is the target every policy
instrument in the sweep must be calibrated to recover.

Per agent:
    daily_base_VMT   = (sum of link lengths over iter-0 'left link' events) / N_DAYS
    electric_VMT     = daily_base_VMT * UF        (UF = per-agent utilityFactor for
                                                   PHEVs; 1.0 for BEVs)
    gallons_displaced= electric_VMT / mpg_counterfactual_archetype
    state_tax_gap    = gallons_displaced * $0.466/gal        (MD state, Jul-2026)
    R*               = sum over agents, annualized.

Why iter-0 events (not the final iteration):
  Charging activities are ADDED during replanning; iter-0 plans contain none, so
  iter-0 travel is the pure activity-chain mobility demand — the correct ICE
  counterfactual (an equivalent ICE would make the same base trips, NOT the extra
  drive-to-public-charger detours that later iterations insert). Activity locations
  are fixed across the run (no location/time mutation strategy), so base VMT is
  stable; iter-0 is both correct and available before the run converges.

Why divide by N_DAYS:
  Plans are ~3-day chains (verified: every agent's last activity ends 53-71 h, i.e.
  day 3; workers make 3 commutes). Iter-0 event distance is therefore ~3 days of
  travel; dividing by 3 gives mean daily VMT. (The legacy compute_per_agent_vmt.py
  omitted this -> ~3x inflation. Fixed here.)

Sources:
  - counterfactual mpg per archetype: research/ev_counterfactual_mpg_lookup.csv
    (EPA fueleconomy.gov; 57 archetypes)
  - MD state fuel tax $0.466/gal (research/md_gas_tax_baseline_2026.md); federal
    $0.184/gal reported as sensitivity
  - annualization: weekday-weighted x348 (252 weekdays + 0.85*113 weekend days),
    per research/md_gas_tax_baseline_2026.md; x365 and x260 shown as bounds
"""
from __future__ import annotations
import argparse
import csv
import gzip
import re
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO.parent
NETWORK = PROJECT / "Input/network/maryland-network-pt2matsim.xml.gz"
EVS = PROJECT / "Input/vehicles/electric_vehicles.xml"
PLANS = PROJECT / "Input/population/plans_maryland_ev_2026.xml.gz"
MPG_LOOKUP = PROJECT / "research/ev_counterfactual_mpg_lookup.csv"

M_PER_MI = 1609.344
STATE_TAX = 0.466       # MD state $/gal (Jul 2026)
FED_TAX = 0.184         # federal $/gal (sensitivity)
ANNUAL = {"x348_weekday_weighted": 348.0, "x365_all_days": 365.0,
          "x260_weekday_only": 260.0}


def load_link_lengths():
    pat = re.compile(r'<link id="([^"]+)"[^>]*length="([0-9.eE+\-]+)"')
    n2l = {}
    with gzip.open(NETWORK, "rt", encoding="utf-8") as f:
        for line in f:
            m = pat.search(line)
            if m:
                n2l[m.group(1)] = float(m.group(2))
    return n2l


def load_vehicle_types():
    pat = re.compile(r'<vehicle id="([^"]+)"[^>]*vehicle_type="([^"]+)"')
    v2t = {}
    with open(EVS, encoding="utf-8") as f:
        for line in f:
            m = pat.search(line)
            if m:
                v2t[m.group(1)] = m.group(2)
    return v2t


def load_mpg_lookup():
    mpg = {}
    with open(MPG_LOOKUP, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                mpg[r["ev_type"]] = float(r["counterfactual_ice_mpg_combined"])
            except (ValueError, KeyError):
                pass
    return mpg


def load_person_attrs():
    """person_id -> (income, income_bucket, evType, utilityFactor)."""
    attrs = {}
    cur = {}
    pid = None
    ra = re.compile(r'<attribute name="(\w+)"[^>]*>([^<]*)</attribute>')
    with gzip.open(PLANS, "rt", encoding="utf-8", newline="") as f:
        for line in f:
            m = re.search(r'<person id="([^"]+)"', line)
            if m:
                if pid:
                    attrs[pid] = cur
                pid = m.group(1); cur = {}
            am = ra.search(line)
            if am:
                cur[am.group(1)] = am.group(2).strip()
        if pid:
            attrs[pid] = cur
    return attrs


def parse_events(link_len, events_path):
    pat = re.compile(r'type="left link"[^/]*vehicle="([^"]+)"[^/]*link="([^"]+)"')
    pat_alt = re.compile(r'type="left link"[^/]*link="([^"]+)"[^/]*vehicle="([^"]+)"')
    veh_m = defaultdict(float)
    n = 0; miss = 0; t0 = time.time()
    with gzip.open(events_path, "rt", encoding="utf-8") as f:
        for line in f:
            if "left link" not in line:
                continue
            m = pat.search(line)
            if m:
                vid, lid = m.group(1), m.group(2)
            else:
                m = pat_alt.search(line)
                if not m:
                    continue
                lid, vid = m.group(1), m.group(2)
            L = link_len.get(lid)
            if L is None:
                miss += 1; continue
            veh_m[vid] += L
            n += 1
            if n % 20_000_000 == 0:
                print(f"  {n:,} events ({n/(time.time()-t0)/1e6:.1f}M/s)", flush=True)
    print(f"  done: {n:,} events, {miss:,} unknown-link, "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    return veh_m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=Path,
                    default=REPO / "scenarios/maryland/output/runs_2026/baseline/ITERS/it.0/0.events.xml.gz")
    ap.add_argument("--n-days", type=float, default=3.0,
                    help="day-cycles per plan (plans span day 3; default 3)")
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out_dir or args.events.parents[2]   # -> output/final_runs/baseline_v2/

    if not args.events.exists():
        raise SystemExit(f"events not found: {args.events}")

    print("[1/5] link lengths ..."); link_len = load_link_lengths()
    print(f"      {len(link_len):,} links")
    print("[2/5] vehicle types ..."); v2t = load_vehicle_types()
    print("[3/5] mpg lookup + person attrs ...")
    mpg = load_mpg_lookup(); attrs = load_person_attrs()
    print(f"      {len(mpg)} archetypes, {len(attrs):,} persons")
    print(f"[4/5] streaming events {args.events.name} ...")
    veh_m = parse_events(link_len, args.events)

    print("[5/5] computing per-agent shadow tax ...")
    default_mpg = 25.0
    rows = []
    tot = defaultdict(float)
    by_decile = defaultdict(lambda: defaultdict(float))
    n_missing_mpg = 0
    for vid, vt in v2t.items():
        # vehicle id shh_XXXX_ev1 -> person id shh_XXXX_ev1 (same key in plans)
        a = attrs.get(vid, {})
        et = a.get("evType", "BEV")
        uf = 1.0
        if et.upper() == "PHEV":
            try: uf = float(a.get("utilityFactor", "1.0"))
            except ValueError: uf = 1.0
        mpg_cf = mpg.get(vt)
        if mpg_cf is None:
            mpg_cf = default_mpg; n_missing_mpg += 1
        daily_vmt = (veh_m.get(vid, 0.0) / M_PER_MI) / args.n_days
        elec_vmt = daily_vmt * uf
        gal_day = elec_vmt / mpg_cf
        state_day = gal_day * STATE_TAX
        income = a.get("income", "")
        dec = a.get("hh_income_detailed", "")
        rows.append((vid, vt, et, round(uf, 4), round(daily_vmt, 4),
                     round(elec_vmt, 4), round(mpg_cf, 1), round(gal_day, 5),
                     round(state_day, 5), income, dec))
        tot["daily_vmt"] += daily_vmt
        tot["elec_vmt"] += elec_vmt
        tot["gal_day"] += gal_day
        tot["state_day"] += state_day
        if dec:
            by_decile[dec]["state_day"] += state_day
            by_decile[dec]["elec_vmt"] += elec_vmt
            by_decile[dec]["n"] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    per_agent = out_dir / "shadow_tax_gap_per_agent.csv"
    with per_agent.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["vehicle_id", "vehicle_type", "ev_type", "uf",
                    "daily_base_vmt_mi", "daily_elec_vmt_mi", "mpg_counterfactual",
                    "gal_displaced_day", "state_tax_gap_day_usd",
                    "income_usd", "income_decile"])
        w.writerows(rows)

    # R* under each annualization
    lines = ["=== SHADOW TAX GAP R* (from iter-0 base mobility) ===",
             f"events        : {args.events}",
             f"n_days divisor: {args.n_days}",
             f"vehicles      : {len(rows):,}  "
             f"(zero-VMT: {sum(1 for r in rows if r[4]==0):,}; "
             f"missing-mpg->25: {n_missing_mpg:,})",
             f"daily base VMT: {tot['daily_vmt']:,.0f} mi/day "
             f"({tot['daily_vmt']/len(rows):.1f} mi/veh/day)",
             f"daily elec VMT: {tot['elec_vmt']:,.0f} mi/day",
             f"daily gallons : {tot['gal_day']:,.0f} gal/day displaced",
             ""]
    for label, factor in ANNUAL.items():
        Rstate = tot["state_day"] * factor
        Rfed = tot["gal_day"] * FED_TAX * factor
        lines.append(f"R* [{label:24}] state ${Rstate/1e6:7.2f}M/yr   "
                     f"(+fed ${Rfed/1e6:.2f}M = ${ (Rstate+Rfed)/1e6:.2f}M combined)")
    lines += ["",
              "Sanity vs flat proxy (100k EV x 480 gal x $0.466 = $22.4M):",
              f"  simulated state R* (x348) = "
              f"${tot['state_day']*348/1e6:.2f}M  "
              f"[>25% divergence would flag a modeling issue]"]

    # per-decile equity table (weekday-weighted x348)
    lines += ["", "Per income-decile shadow tax (state, x348 weekday-weighted):",
              f"  {'decile':>6} {'n':>7} {'$/yr total':>14} {'$/agent/yr':>12}"]
    for d in sorted(by_decile, key=lambda x: (len(x), x)):
        v = by_decile[d]; R = v["state_day"] * 348
        lines.append(f"  {d:>6} {int(v['n']):>7} {R:>14,.0f} "
                     f"{R/v['n']:>12,.0f}")

    summary = out_dir / "shadow_tax_gap_summary.txt"
    txt = "\n".join(lines)
    summary.write_text(txt + "\n")
    print("\n" + txt)
    print(f"\n[wrote] {per_agent.relative_to(REPO)}")
    print(f"[wrote] {summary.relative_to(REPO)}")


if __name__ == "__main__":
    main()
