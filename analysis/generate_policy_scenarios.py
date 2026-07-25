#!/usr/bin/env python3
"""
generate_policy_scenarios.py — emit MATSim XML configs for shadow-tax recovery
policy scenarios from a parameter table.

Reads:  analysis/policy_scenarios.csv
        scenarios/maryland/config_baseline_calibrated_v2b_100pct.xml (template)
Writes: scenarios/maryland/policy/<scenario_id>.xml  (one per CSV row)

Each scenario inherits the v2b baseline config and overrides only:
  - homeChargingCost
  - publicL2Cost
  - publicDcfcCost
  - publicDcfcTeslaCost
  - controler.outputDirectory  -> output/policy/<scenario_id>/

The header comment is rewritten to document the policy intent and the
Δ-from-baseline ($0.139/$0.27/$0.43/$0.40) so downstream readers can audit.
"""
from __future__ import annotations
import csv
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "scenarios" / "maryland" / "config_baseline_calibrated_v2b_100pct.xml"
TABLE = REPO / "analysis" / "policy_scenarios.csv"
OUT_DIR = REPO / "scenarios" / "maryland" / "policy"

BASELINE = {"home": 0.139, "l2": 0.27, "dcfc": 0.43, "tesla": 0.40}


def header_comment(sid: str, desc: str, h: float, l2: float, dc: float, tt: float) -> str:
    dh, dl, dd, dt = h - BASELINE["home"], l2 - BASELINE["l2"], dc - BASELINE["dcfc"], tt - BASELINE["tesla"]
    return (
        "<!--\n"
        f"  Maryland UrbanEV — Phase 7 policy scenario {sid}\n"
        f"  {desc}\n"
        f"\n"
        f"  Δ-from-baseline (cents/kWh):\n"
        f"    home  : {dh*100:+.1f}    (= ${h:.3f}/kWh)\n"
        f"    L2    : {dl*100:+.1f}    (= ${l2:.3f}/kWh)\n"
        f"    DCFC  : {dd*100:+.1f}    (= ${dc:.3f}/kWh)\n"
        f"    Tesla : {dt*100:+.1f}    (= ${tt:.3f}/kWh)\n"
        f"\n"
        f"  Output: output/policy/{sid}/\n"
        f"  All other params identical to config_baseline_calibrated_v2b_100pct.xml.\n"
        "-->"
    )


def patch_one(text: str, sid: str, row: dict) -> str:
    h, l2, dc, tt = float(row["home_cost"]), float(row["l2_cost"]), float(row["dcfc_cost"]), float(row["tesla_cost"])
    # Replace header comment block (first <!-- ... --> after the DOCTYPE)
    text = re.sub(
        r"<!--.*?-->",
        header_comment(sid, row["description"], h, l2, dc, tt),
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Cost overrides
    text = re.sub(
        r'<param name="homeChargingCost"\s+value="[^"]+"',
        f'<param name="homeChargingCost" value="{h}"',
        text, count=1,
    )
    text = re.sub(
        r'<param name="publicL2Cost"\s+value="[^"]+"',
        f'<param name="publicL2Cost" value="{l2}"',
        text, count=1,
    )
    text = re.sub(
        r'<param name="publicDcfcCost"\s+value="[^"]+"',
        f'<param name="publicDcfcCost" value="{dc}"',
        text, count=1,
    )
    text = re.sub(
        r'<param name="publicDcfcTeslaCost"\s+value="[^"]+"',
        f'<param name="publicDcfcTeslaCost" value="{tt}"',
        text, count=1,
    )
    # Output dir
    text = re.sub(
        r'<param name="outputDirectory"\s+value="[^"]+"',
        f'<param name="outputDirectory" value="output/policy/{sid}"',
        text, count=1,
    )
    # Bump Input-file relative paths from "../../../Input/" (baseline depth, scenarios/maryland/)
    # to "../../../../Input/" (policy depth, scenarios/maryland/policy/)
    text = text.replace('value="../../../Input/', 'value="../../../../Input/')
    return text


def main() -> int:
    if not TEMPLATE.exists():
        print(f"ERROR: template not found: {TEMPLATE}")
        return 2
    if not TABLE.exists():
        print(f"ERROR: parameter table not found: {TABLE}")
        return 2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base_text = TEMPLATE.read_text(encoding="utf-8")

    written = 0
    with TABLE.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row["scenario_id"].strip()
            if not sid or sid.startswith("#"):
                continue
            patched = patch_one(base_text, sid, row)
            out = OUT_DIR / f"{sid}.xml"
            out.write_text(patched, encoding="utf-8")
            print(f"[wrote] {out.relative_to(REPO)}")
            written += 1
    print(f"\n{written} scenario config(s) written to {OUT_DIR.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
