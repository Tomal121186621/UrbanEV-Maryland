#!/usr/bin/env python3
"""Generate charging-surcharge PRICE-SWEEP configs, warm-started from the per-type baseline.
Sweep escalates the surcharge far past the feasible range to expose the Laffer ceiling and the
behavioral substitution (home-charger owners flee public -> taxable base collapses to captives).
Public sweep: add X c/kWh to all public types (home fixed at baseline 0.139).
Home sweep:   add Y c/kWh to home (public fixed at baseline 0.27/0.43/0.40).
-> config_sweep_<name>.xml   (each warm-starts from baseline_pertype/output_plans.xml.gz)"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = (HERE / "config_baseline_2026_pertype.xml").read_text()

# baseline per-type prices
H0, L20, DC0, TE0 = 0.139, 0.27, 0.43, 0.40

# (name, home, l2, dcfc, tesla)  — public sweep then home sweep
SCEN = []
for c in [10, 25, 50, 100, 150, 200]:                       # public surcharge (cents)
    x = c / 100
    SCEN.append((f"pub_{c}c", H0, round(L20 + x, 3), round(DC0 + x, 3), round(TE0 + x, 3)))
for c in [10, 22, 40]:                                       # home surcharge (cents)
    y = c / 100
    SCEN.append((f"home_{c}c", round(H0 + y, 3), L20, DC0, TE0))

WARM = "output/runs_2026/baseline_pertype/output_plans.xml.gz"


def sub(txt, param, val):
    return re.sub(rf'(<param name="{param}" value=")[^"]*(")', rf'\g<1>{val}\g<2>', txt)


for name, h, l2, dc, te in SCEN:
    t = TEMPLATE
    t = sub(t, "homeChargingCost", h)
    t = sub(t, "publicL2Cost", l2)
    t = sub(t, "publicDcfcCost", dc)
    t = sub(t, "publicDcfcTeslaCost", te)
    t = sub(t, "inputPlansFile", WARM)
    t = sub(t, "outputDirectory", f"output/runs_2026/sweep_{name}")
    t = sub(t, "lastIteration", 8)           # warm-started reconvergence (charging re-opt only)
    out = HERE / f"config_sweep_{name}.xml"
    out.write_text(t)
    print(f"{out.name:28s} home={h:<5} L2={l2:<5} DCFC={dc:<5} Tesla={te}")

print(f"\n{len(SCEN)} sweep configs written. Batches: "
      "[pub_10c,pub_25c,pub_50c] [pub_100c,pub_150c,pub_200c] [home_10c,home_22c,home_40c]")
