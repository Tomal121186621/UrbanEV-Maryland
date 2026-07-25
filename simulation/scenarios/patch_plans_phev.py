#!/usr/bin/env python3
"""In-place PHEV-fallback patch for EXISTING validated EV plans + fleet files (no
regeneration -> full comparability with prior runs). Two changes only:
  1. plans: add phevGasCostPerKwh attribute to PHEV agents (evModel -> rate from
     research/phev_gas_fallback_costs.csv).
  2. fleet: PHEV charger_types -> "L1,L2" for L2-only archetypes (18/21 per
     urbanev_vehicletypes.xml comments), "L1,L2,DCFC" for the DCFC-capable rest.
Writes <name>_phev.xml(.gz) siblings; originals untouched."""
import gzip, re, sys
from pathlib import Path
import pandas as pd

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
COST = dict(pd.read_csv(ROOT/"research/phev_gas_fallback_costs.csv")[["ev_type","gas_cost_per_kwh"]].values)
L2ONLY = {re.search(r'name="([^"]+)"', ln).group(1)
          for ln in open(ROOT/"Input/vehicles/urbanev_vehicletypes.xml") if "L2 only" in ln}

def patch_plans(src, dst):
    op = gzip.open if str(src).endswith(".gz") else open
    n = 0
    with op(src, "rt") as f, op(dst, "wt") as o:
        model = None
        for ln in f:
            if "evModel" in ln:
                m = re.search(r">([^<]+)</attribute>", ln); model = m.group(1) if m else None
            if 'name="utilityFactor"' in ln and model in COST:
                o.write(ln)
                o.write(f'\t\t\t<attribute name="phevGasCostPerKwh" class="java.lang.Double">{COST[model]:.4f}</attribute>\n')
                n += 1; model = None
                continue
            if "</person>" in ln: model = None
            o.write(ln)
    print(f"[plans] {src.name}: {n:,} PHEV agents patched -> {dst.name}")

def patch_fleet(src, dst):
    n = 0
    with open(src) as f, open(dst, "w") as o:
        for ln in f:
            m = re.search(r'vehicle_type="([^"]+)"', ln)
            if m and m.group(1) in L2ONLY:
                ln2 = re.sub(r'charger_types="[^"]*"', 'charger_types="L1,L2"', ln)
                if ln2 != ln: n += 1
                ln = ln2
            elif m and "phev" in m.group(1) or (m and m.group(1) in COST):
                # DCFC-capable PHEV: strip DCFC_TESLA if present (Tesla-only), keep DCFC
                ln2 = re.sub(r'charger_types="[^"]*"', 'charger_types="L1,L2,DCFC"', ln) \
                      if m.group(1) in COST and m.group(1) not in L2ONLY else ln
                if ln2 != ln: n += 1
                ln = ln2
            o.write(ln)
    print(f"[fleet] {src.name}: {n:,} vehicles re-permissioned -> {dst.name}")

if __name__ == "__main__":
    S = ROOT/"UrbanEV-Maryland/scenarios/maryland/sample_25pct"
    patch_plans(S/"plans_25pct.xml.gz", S/"plans_25pct_phev.xml.gz")
    patch_fleet(S/"electric_vehicles_25pct.xml", S/"electric_vehicles_25pct_phev.xml")
    patch_plans(ROOT/"Input/population/plans_maryland_ev_2026.xml.gz",
                ROOT/"Input/population/plans_maryland_ev_2026_phev.xml.gz")
    patch_fleet(ROOT/"Input/vehicles/electric_vehicles.xml",
                ROOT/"Input/vehicles/electric_vehicles_phev.xml")
