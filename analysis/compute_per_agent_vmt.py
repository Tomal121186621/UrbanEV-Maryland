#!/usr/bin/env python3
"""
compute_per_agent_vmt.py — exact per-vehicle daily VMT and electric-VMT
from MATSim iter-0 events.

Reads:
  Input/network/maryland-network-pt2matsim.xml.gz   (link -> length_m)
  Input/vehicles/electric_vehicles_clean.xml         (vehicle_id -> vehicle_type)
  Input/vehicles/phev_uf.csv                         (vehicle_type -> UF) [via name map]
  output/baseline_calibrated_v2b_100pct/ITERS/it.0/0.events.xml.gz

Writes:
  output/baseline_calibrated_v2b_100pct/per_agent_vmt.csv
    columns: vehicle_id, vehicle_type, is_phev, uf, vmt_mi_day,
             elec_vmt_mi_day, gas_vmt_mi_day

Computes:
  - per-vehicle daily VMT (sum link.length over 'entered link' events)
  - electric VMT = BEV ? VMT : VMT * UF
  - fleet aggregates + annualized shadow-tax target (weekday-only x260)

Stream-parsing: events file is ~2.7 GB compressed; we scan line-by-line with
gzip.open + regex match on 'left link' events to avoid full XML parse.
"""
from __future__ import annotations
import gzip
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO.parent
NETWORK = PROJECT / "Input" / "network" / "maryland-network-pt2matsim.xml.gz"
EVS     = PROJECT / "Input" / "vehicles" / "electric_vehicles_clean.xml"
UF_CSV  = PROJECT / "Input" / "vehicles" / "phev_uf.csv"
EVENTS  = REPO / "output" / "baseline_calibrated_v2b_100pct" / "ITERS" / "it.0" / "0.events.xml.gz"
OUT_CSV = REPO / "output" / "baseline_calibrated_v2b_100pct" / "per_agent_vmt.csv"
OUT_SUMMARY = REPO / "output" / "baseline_calibrated_v2b_100pct" / "per_agent_vmt_summary.txt"

# vehicle_type strings in electric_vehicles_clean.xml that correspond to PHEVs
# (per Input/vehicles/phev_uf.csv rows). UF values from EPA AER -> UF formula.
PHEV_UF = {
    'rav4_prime':0.72, 'x5_x3_330e_530e':0.58, 'prius_prime':0.74,
    'wrangler_4xe':0.456, 'nx_rx_phev':0.664, 'xc60_s60_s90_phev':0.64,
    'grand_cherokee_4xe':0.51, 'gle_glc_s_class_phev':0.77,
    'outlander_phev':0.676, 'cayenne_panamera_phev':0.366,
    'pacifica_hybrid':0.604, 'tucson_phev':0.616, 'escape_phev':0.664,
    'aviator_corsair_phev':0.438, 'range_rover_phev':0.78, 'q5_e':0.474,
    'sportage_phev':0.628, 'sorento_phev':0.604, 'santa_fe_phev':0.58,
    'cx_90_phev':0.524, 'other_phev_mainstream':0.616,
}


def load_link_lengths() -> dict:
    """Return {link_id: length_m}. Uses regex to avoid full DOM parse."""
    print(f"[network] reading {NETWORK.name} ...", flush=True)
    pat = re.compile(r'<link id="([^"]+)"[^>]*length="([0-9.eE+\-]+)"')
    n2l = {}
    t0 = time.time()
    with gzip.open(NETWORK, 'rt', encoding='utf-8') as f:
        for line in f:
            for m in pat.finditer(line):
                n2l[m.group(1)] = float(m.group(2))
    print(f"          {len(n2l):,} links in {time.time()-t0:.1f}s", flush=True)
    return n2l


def load_vehicle_types() -> dict:
    """Return {vehicle_id: vehicle_type}."""
    print(f"[vehicles] reading {EVS.name} ...", flush=True)
    pat = re.compile(r'<vehicle id="([^"]+)"[^>]*vehicle_type="([^"]+)"')
    v2t = {}
    with open(EVS, 'r', encoding='utf-8') as f:
        for line in f:
            m = pat.search(line)
            if m:
                v2t[m.group(1)] = m.group(2)
    print(f"          {len(v2t):,} vehicles", flush=True)
    return v2t


def parse_events_per_vehicle(link_len: dict) -> dict:
    """
    Sum link length per vehicle from 'left link' events. We use 'left link'
    (not 'entered link') because MATSim emits 'left link' on link departure
    with the full link traversal completed — matches VMT semantics.
    Returns {vehicle_id: meters_traveled}.
    """
    print(f"[events] streaming {EVENTS.name} (~2.7GB compressed) ...", flush=True)
    # match: <event time="..." type="left link" vehicle="..." link="..." />
    pat = re.compile(r'type="left link"[^/]*vehicle="([^"]+)"[^/]*link="([^"]+)"')
    # also tolerant of attribute-order swap
    pat_alt = re.compile(r'type="left link"[^/]*link="([^"]+)"[^/]*vehicle="([^"]+)"')

    veh_m = defaultdict(float)
    missing_links = 0
    n_events = 0
    t0 = time.time()
    last_report = t0
    with gzip.open(EVENTS, 'rt', encoding='utf-8') as f:
        for line in f:
            if 'left link' not in line:
                continue
            m = pat.search(line)
            if m is None:
                m = pat_alt.search(line)
                if m is None:
                    continue
                link_id, veh_id = m.group(1), m.group(2)
            else:
                veh_id, link_id = m.group(1), m.group(2)
            L = link_len.get(link_id)
            if L is None:
                missing_links += 1
                continue
            veh_m[veh_id] += L
            n_events += 1
            if n_events % 5_000_000 == 0:
                dt = time.time() - t0
                print(f"          {n_events:,} 'left link' events  "
                      f"({n_events/dt/1e6:.2f}M/s)  "
                      f"vehicles_seen={len(veh_m):,}", flush=True)
    print(f"          DONE: {n_events:,} 'left link' events in "
          f"{(time.time()-t0)/60:.1f} min", flush=True)
    if missing_links:
        print(f"          WARN: {missing_links:,} events had unknown link IDs", flush=True)
    return dict(veh_m)


def main() -> int:
    if not EVENTS.exists():
        print(f"ERROR: events file not found: {EVENTS}")
        return 2

    link_len = load_link_lengths()
    veh_type = load_vehicle_types()
    veh_m = parse_events_per_vehicle(link_len)

    # join
    print(f"[join] {len(veh_m):,} vehicles seen in events / "
          f"{len(veh_type):,} total in fleet", flush=True)

    M_PER_MI = 1609.344
    rows = []
    n_bev = n_phev = 0
    sum_vmt = 0.0
    sum_elec = 0.0
    sum_gas = 0.0
    unknown_types = defaultdict(int)
    for vid, vt in veh_type.items():
        m = veh_m.get(vid, 0.0)
        vmt_mi = m / M_PER_MI
        is_phev = vt in PHEV_UF
        uf = PHEV_UF.get(vt, 1.0)  # BEV -> UF=1.0 by convention
        elec_mi = vmt_mi * uf
        gas_mi = vmt_mi * (1.0 - uf)
        rows.append((vid, vt, int(is_phev), uf, vmt_mi, elec_mi, gas_mi))
        sum_vmt += vmt_mi
        sum_elec += elec_mi
        sum_gas += gas_mi
        if is_phev: n_phev += 1
        else:
            n_bev += 1
            # sanity: if not in PHEV map, confirm it's a known BEV type. We don't
            # have a canonical BEV list; track types so we can audit.
            unknown_types[vt] += 1  # counts ALL non-PHEV types; pruned in report

    # write per-agent csv
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open('w', encoding='utf-8') as f:
        f.write("vehicle_id,vehicle_type,is_phev,uf,vmt_mi_day,elec_vmt_mi_day,gas_vmt_mi_day\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]},{r[2]},{r[3]:.4f},{r[4]:.4f},{r[5]:.4f},{r[6]:.4f}\n")
    print(f"[wrote] {OUT_CSV.relative_to(REPO)}  ({len(rows):,} rows)", flush=True)

    # shadow tax (assume 25 mpg counterfactual, $0.466/gal MD)
    MPG = 25.0
    TAX = 0.466
    elec_yr_wd  = sum_elec * 260
    elec_yr_365 = sum_elec * 365
    tax_yr_wd   = elec_yr_wd  / MPG * TAX
    tax_yr_365  = elec_yr_365 / MPG * TAX

    lines = []
    lines.append("=== per-agent VMT summary (iter 0 events, ground truth) ===")
    lines.append(f"fleet : BEV {n_bev:,} ({100*n_bev/len(veh_type):.2f}%)  "
                 f"PHEV {n_phev:,} ({100*n_phev/len(veh_type):.2f}%)")
    lines.append(f"sim day:")
    lines.append(f"  total fleet VMT   : {sum_vmt:>14,.0f} mi/day  "
                 f"({sum_vmt/len(veh_type):.1f} mi/veh)")
    lines.append(f"  electric VMT      : {sum_elec:>14,.0f} mi/day  "
                 f"({100*sum_elec/sum_vmt:.2f}% of total)")
    lines.append(f"  gasoline VMT (PHEV CS): {sum_gas:>10,.0f} mi/day  "
                 f"({100*sum_gas/sum_vmt:.2f}% of total)")
    lines.append("")
    lines.append(f"shadow-tax target @ {MPG} mpg, ${TAX}/gal:")
    lines.append(f"  x260 weekdays/yr : ${tax_yr_wd/1e6:.2f}M/yr  "
                 f"(electric VMT {elec_yr_wd/1e9:.2f}B mi)")
    lines.append(f"  x365 days/yr     : ${tax_yr_365/1e6:.2f}M/yr  "
                 f"(electric VMT {elec_yr_365/1e9:.2f}B mi)")
    lines.append("")
    lines.append(f"(zero-VMT vehicles in events: "
                 f"{sum(1 for r in rows if r[4]==0.0):,} of {len(rows):,})")

    txt = "\n".join(lines)
    print()
    print(txt)
    OUT_SUMMARY.write_text(txt + "\n", encoding='utf-8')
    print(f"\n[wrote] {OUT_SUMMARY.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
