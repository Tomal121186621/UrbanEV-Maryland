#!/usr/bin/env python3
"""
make_sample.py — build a downscaled MATSim scenario for the calibration/sweep campaign.

Deterministic household/agent subsample (hash of person id → stable across all runs) +
charger-network scaling per the MATSim downscaling convention:
  plans/vehicles : keep fraction f of agents
  chargers       : plug_count -> max(1, round(plug_count*f))   (integer-capacity min 1)
  (flowCapacityFactor=f, storageCapacityFactor=f**0.75 are set in the config, not here)

Usage: make_sample.py 0.25
Writes to scenarios/maryland/sample_<pct>/: plans, electric_vehicles, chargers.
"""
import gzip, sys, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]                 # UrbanEV-Maryland
REPO = ROOT.parent
f = float(sys.argv[1]) if len(sys.argv) > 1 else 0.25
pct = f"{int(round(f*100))}pct"
OUT = ROOT / "scenarios" / "maryland" / f"sample_{pct}"
OUT.mkdir(parents=True, exist_ok=True)
IN_PLANS = REPO / "Input/population/plans_maryland_ev_2026.xml.gz"
IN_VEH = REPO / "Input/vehicles/electric_vehicles.xml"
IN_CHG = REPO / "Input/chargers/chargers.xml"

thr = int(f * 1_000_000)
def keep(pid):
    return int(hashlib.md5(pid.encode()).hexdigest(), 16) % 1_000_000 < thr

# ---- plans ----
ids = set(); npers = 0
with gzip.open(IN_PLANS, "rt") as fi, gzip.open(OUT / f"plans_{pct}.xml.gz", "wt") as fo:
    buf = []; inper = False; keeping = False
    for ln in fi:
        s = ln.lstrip()
        if s.startswith(("<?xml", "<!DOCTYPE", "<population")):
            fo.write(ln); continue
        if "<person " in ln:
            pid = ln.split('id="')[1].split('"')[0]
            keeping = keep(pid)
            if keeping:
                buf = [ln]; ids.add(pid); inper = True
            continue
        if inper:
            buf.append(ln)
            if "</person>" in ln:
                fo.write("".join(buf)); inper = False; npers += 1
    fo.write("</population>\n")

# ---- vehicles (matching ids) ----
nveh = 0
with open(IN_VEH) as fi, open(OUT / f"electric_vehicles_{pct}.xml", "w") as fo:
    for ln in fi:
        s = ln.lstrip()
        if s.startswith(("<?xml", "<!DOCTYPE", "<vehicles")):
            fo.write(ln); continue
        if "<vehicle " in ln:
            vid = ln.split('id="')[1].split('"')[0]
            if vid in ids:
                fo.write(ln); nveh += 1
    fo.write("</vehicles>\n")

# ---- chargers (scale plug_count, min 1) ----
import re
nchg = 0; plugs = 0
txt = IN_CHG.read_text().splitlines()
with open(OUT / f"chargers_{pct}.xml", "w") as fo:
    for ln in txt:
        m = re.search(r'plug_count="(\d+)"', ln)
        if m:
            pc = max(1, round(int(m.group(1)) * f))
            ln = ln[:m.start()] + f'plug_count="{pc}"' + ln[m.end():]
            nchg += 1; plugs += pc
        fo.write(ln + "\n")

print(f"[sample {pct}] persons={npers:,} vehicles={nveh:,} chargers={nchg} scaled_plugs={plugs:,}")
print(f"  -> {OUT}")
