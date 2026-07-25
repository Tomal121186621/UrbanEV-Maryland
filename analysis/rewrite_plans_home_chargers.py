#!/usr/bin/env python3
"""
rewrite_plans_home_chargers.py — DRY-RUN by default.

Data-driven replacement for the current ~89.8% blanket home-charger flag.
Applies a two-stage probability model per agent:

  P(home_charger | agent)
    = P(garage/off_street | dwellingType, homeOwnership)     [ACS + Ge et al. 2021]
    × P(installed | eligible, income, evType)                [JD Power 2024, PIA 2024]

Sources (see output/phase_R_calibration/diagnosis_v2/home_charger_rate_sources.csv):
  - Ge et al. 2021 NREL TP-5400-81065 (residential parking + electrical access)
  - Wood, Borlaug et al. 2023 NREL TP-5400-85654 (2030 National Charging Network)
  - Plug In America 2024 EV Driver Survey
  - JD Power 2024 EVX Home Charging Study
  - US Census ACS 5-yr (Baltimore-Columbia-Towson MSA housing tenure)

Modes
-----
  --dry-run   (default) : count-only, no writes to plans.
              Emits an assignment manifest and predicted aggregate rate.
  --write     : disabled until user approves. Placeholder raises NotImplementedError.

Usage
-----
  python analysis/rewrite_plans_home_chargers.py --dry-run
"""
from __future__ import annotations
import argparse
import gzip
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # repo root containing Input/ (portable; was hardcoded Windows path)
PLANS_IN = ROOT / "Input/population/plans_maryland_ev_clean_anx020.xml.gz"

OUT_DIR = ROOT / "UrbanEV-Maryland/output/phase_R_calibration/diagnosis_v2"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Probability tables (all values cited to a source; do NOT edit without a cite)
# ---------------------------------------------------------------------------

# P(garage or off-street parking with electrical access | dwelling × ownership)
# Anchored on Ge et al. 2021 (NREL 81065) which reports:
#   - 94% of SFD garages have or could have electrical access
#   - <50% of driveway/carport homes
#   - <25% of apartments
# Refined by ownership: renters have less capital / permission to install →
# subtract ~15-20 pp for rent within same dwelling class (Plug In America 2024,
# JD Power 2024 — both flag MUD/rental as chronically under-installed).
P_GARAGE = {
    # dwelling  ownership  P(off-street w/ electrical access)
    ("SFD",    "own"):   0.94,   # Ge 2021 – detached w/ garage
    ("SFD",    "rent"):  0.75,   # Ge 2021 driveway/carport tier, rent penalty
    ("SFD",    "other"): 0.75,
    ("SFA",    "own"):   0.75,   # townhouse/attached SF; often garage or driveway
    ("SFA",    "rent"):  0.55,
    ("SFA",    "other"): 0.55,
    ("Apt",    "own"):   0.35,   # condo w/ deeded parking
    ("Apt",    "rent"):  0.20,   # Ge 2021 apartment tier
    ("Apt",    "other"): 0.20,
    ("Mobile", "own"):   0.60,   # mobile parks typically have off-street
    ("Mobile", "rent"):  0.55,
    ("Mobile", "other"): 0.55,
}

# P(installed a home L2 | eligible for install, income tier, evType)
# Income tiers based on hh_income_detailed bucket (1..8 = ACS income deciles):
#   1: <$25k, 2: $25-35k, 3: $35-50k, 4: $50-75k,
#   5: $75-100k, 6: $100-150k, 7: $150-200k, 8: >$200k
# Anchors:
#   JD Power 2024 EVX: 84% of home-chargers-users use L2 among EV owners
#   Plug In America 2024: install correlates strongly w/ income and BEV vs PHEV
#   PHEVs frequently use L1 (occupant satisfaction w/ L1 for PHEV higher)
P_INSTALL = {
    # (income bucket, ev type)  -> P(actually installed | off-street parking)
    (1, "BEV"):  0.45,  (1, "PHEV"): 0.30,
    (2, "BEV"):  0.55,  (2, "PHEV"): 0.35,
    (3, "BEV"):  0.65,  (3, "PHEV"): 0.45,
    (4, "BEV"):  0.75,  (4, "PHEV"): 0.55,
    (5, "BEV"):  0.82,  (5, "PHEV"): 0.65,
    (6, "BEV"):  0.88,  (6, "PHEV"): 0.72,
    (7, "BEV"):  0.92,  (7, "PHEV"): 0.78,
    (8, "BEV"):  0.94,  (8, "PHEV"): 0.82,
}


def p_garage(dwelling: str, ownership: str) -> float:
    return P_GARAGE.get((dwelling, ownership), 0.55)


def p_install(income_bucket: str, ev_type: str) -> float:
    try:
        b = int(float(income_bucket))
    except Exception:
        b = 5
    et = "PHEV" if ev_type and ev_type.upper() == "PHEV" else "BEV"
    return P_INSTALL.get((b, et), 0.65)


def sample_home_charger(dwelling: str, ownership: str, income_bucket: str,
                        ev_type: str, rng) -> tuple[bool, float]:
    p1 = p_garage(dwelling, ownership)
    p2 = p_install(income_bucket, ev_type)
    p = p1 * p2
    return (rng.random() < p), p


# ---------------------------------------------------------------------------
# Streaming plans read
# ---------------------------------------------------------------------------
def stream_persons(plans_gz: Path, limit: int | None = None):
    """Yield dicts of person attributes."""
    with gzip.open(plans_gz, "rb") as f:
        ctx = ET.iterparse(f, events=("start", "end"))
        cur = None
        n = 0
        for ev, el in ctx:
            if ev == "start" and el.tag == "person":
                cur = {"person_id": el.get("id"), "_attrs": {}}
            elif ev == "end" and el.tag == "attribute" and cur is not None:
                cur["_attrs"][el.get("name")] = (el.text or "").strip()
            elif ev == "end" and el.tag == "person":
                a = cur["_attrs"]
                yield {
                    "person_id":         cur["person_id"],
                    "dwellingType":      a.get("dwellingType", "SFD"),
                    "homeOwnership":     a.get("homeOwnership", "own"),
                    "income_bucket":     a.get("hh_income_detailed", "5"),
                    "evType":            a.get("evType", "BEV"),
                    "homeChargerPower":  a.get("homeChargerPower", "0.0"),
                    "smartChargingAware": a.get("smartChargingAware", "false"),
                }
                cur = None
                el.clear()
                n += 1
                if limit is not None and n >= limit:
                    return


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--write", action="store_true",
                    help="Disabled until user approves. Will raise.")
    ap.add_argument("--seed", type=int, default=20260702)
    ap.add_argument("--limit", type=int, default=None,
                    help="Optional cap on persons for a fast test.")
    args = ap.parse_args()

    if args.write:
        raise NotImplementedError(
            "Write mode disabled. User approval required before "
            "modifying plans_maryland_ev_clean_anx020.xml.gz."
        )

    import random
    rng = random.Random(args.seed)

    n_total = 0
    n_curr_have = 0     # current plan says homeChargerPower > 0
    n_new_have = 0      # model says should have
    bucket_new_have = defaultdict(int)
    bucket_total = defaultdict(int)
    bucket_curr_have = defaultdict(int)
    prob_sum = 0.0
    kw_split = Counter()   # among currently-having, kW distribution
    curr_kw_by_new = defaultdict(Counter)

    for p in stream_persons(PLANS_IN, args.limit):
        n_total += 1
        curr_pow = float(p["homeChargerPower"] or 0.0)
        curr_have = curr_pow > 0.0
        n_curr_have += int(curr_have)

        new_have, prob = sample_home_charger(
            p["dwellingType"], p["homeOwnership"],
            p["income_bucket"], p["evType"], rng,
        )
        n_new_have += int(new_have)
        prob_sum += prob

        key = (p["dwellingType"], p["homeOwnership"], p["income_bucket"])
        bucket_total[key] += 1
        bucket_new_have[key] += int(new_have)
        bucket_curr_have[key] += int(curr_have)

        # among agents *currently* having a charger, preserve the 7.2 vs 1.4 kW split
        if curr_have:
            kw = "7.2" if abs(curr_pow - 7.2) < 0.5 else ("1.4" if abs(curr_pow - 1.4) < 0.5 else f"{curr_pow:.1f}")
            kw_split[kw] += 1
            if new_have:
                curr_kw_by_new[kw]["kept"] += 1
            else:
                curr_kw_by_new[kw]["dropped"] += 1

        if n_total % 100000 == 0:
            print(f"  processed {n_total:,} persons...")

    # Reports
    print("\n=== DRY RUN SUMMARY ===")
    print(f"total persons        : {n_total:,}")
    print(f"CURRENT rate         : {n_curr_have/n_total:6.2%}  ({n_curr_have:,})")
    print(f"MODEL sample rate    : {n_new_have/n_total:6.2%}   ({n_new_have:,})")
    print(f"MODEL expected rate  : {prob_sum/n_total:6.2%}   (analytic E[P])")
    print("\nkW split among current chargers:")
    for kw, cnt in kw_split.most_common():
        print(f"  {kw:>6} kW  : {cnt:,}")
    print("\nOf currently-having agents, model retention:")
    for kw, sub in curr_kw_by_new.items():
        kept = sub["kept"]; dropped = sub["dropped"]
        tot = kept + dropped
        print(f"  {kw:>6} kW  kept={kept:,} dropped={dropped:,} keep-rate={kept/tot:.2%}")

    # Manifest CSV
    rows = []
    for (dw, ow, ib), tot in sorted(bucket_total.items()):
        rows.append({
            "dwelling": dw, "ownership": ow, "income_bucket": ib,
            "n_agents": tot,
            "n_current_have": bucket_curr_have[(dw, ow, ib)],
            "n_model_have":   bucket_new_have[(dw, ow, ib)],
            "current_rate":   bucket_curr_have[(dw, ow, ib)] / tot,
            "model_rate":     bucket_new_have[(dw, ow, ib)] / tot,
            "p_garage":       p_garage(dw, ow),
            # p_install depends on evType too; report BEV as representative
            "p_install_BEV":  p_install(ib, "BEV"),
            "p_install_PHEV": p_install(ib, "PHEV"),
        })
    df = pd.DataFrame(rows)
    manifest = OUT_DIR / "home_charger_assignment_manifest.csv"
    df.to_csv(manifest, index=False)
    print(f"\nManifest: {manifest}")

    # Summary line for reporting
    summary = OUT_DIR / "home_charger_dryrun_summary.txt"
    with summary.open("w", encoding="utf-8") as f:
        f.write("Data-driven home-charger assignment: DRY RUN\n")
        f.write(f"n_total            : {n_total:,}\n")
        f.write(f"current_rate       : {n_curr_have/n_total:.4f}\n")
        f.write(f"model_sample_rate  : {n_new_have/n_total:.4f}\n")
        f.write(f"model_expected_rate: {prob_sum/n_total:.4f}\n")
        f.write("kw_split_current   : " + ", ".join(f"{k}={v}" for k, v in kw_split.items()) + "\n")
    print(f"Summary : {summary}")
    print("\n(write mode disabled — awaiting user approval)\n")


if __name__ == "__main__":
    main()
