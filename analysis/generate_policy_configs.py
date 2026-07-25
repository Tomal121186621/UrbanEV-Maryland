#!/usr/bin/env python3
"""
generate_policy_configs.py — emit 100% warm-started policy configs from policy_scenarios.csv.

Template   : config_baseline_2026.xml (100%)
Warm-start : inputPlansFile -> output/runs_2026/baseline/output_plans.xml.gz (converged
             baseline plans; agents re-optimize charging under the new prices in ~25 iters)
Per scenario overrides: homeChargingCost + per-type public prices (publicL2Cost,
             publicDcfcCost, publicDcfcTeslaCost inserted after publicChargingCost).
Output     : scenarios/maryland/config_policy_<id>.xml  ->  output/runs_2026/policy_<id>_100pct/
"""
import re, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCEN = ROOT / "scenarios" / "maryland"
TEMPLATE = SCEN / "config_baseline_2026.xml"
TABLE = ROOT / "analysis" / "policy_scenarios.csv"
WARM = "output/runs_2026/baseline/output_plans.xml.gz"
LAST_ITER = 15


def build(row):
    sid = row["scenario_id"]
    txt = TEMPLATE.read_text()
    # warm-start from converged baseline plans
    txt = re.sub(r'(inputPlansFile" value=")[^"]*"',
                 rf'\g<1>{WARM}"', txt)
    # home price
    txt = re.sub(r'(name="homeChargingCost" value=")[^"]*"',
                 rf'\g<1>{row["home_cost"]}"', txt)
    # per-type public prices: insert right after the publicChargingCost line
    inject = (f'        <param name="publicL2Cost" value="{row["l2_cost"]}"/>\n'
              f'        <param name="publicDcfcCost" value="{row["dcfc_cost"]}"/>\n'
              f'        <param name="publicDcfcTeslaCost" value="{row["tesla_cost"]}"/>\n')
    txt = re.sub(r'(<param name="publicChargingCost" value="[^"]*"/>\n)',
                 rf'\g<1>{inject}', txt, count=1)
    txt = re.sub(r'(outputDirectory" value=")[^"]*"',
                 rf'\g<1>output/runs_2026/policy_{sid}_100pct"', txt)
    txt = re.sub(r'(name="lastIteration" value=")[^"]*"', rf'\g<1>{LAST_ITER}"', txt)
    p = SCEN / f"config_policy_{sid}.xml"; p.write_text(txt)
    return sid


def main():
    ids = []
    with open(TABLE) as f:
        for row in csv.DictReader(f):
            ids.append(build(row))
    print(f"[policy] wrote {len(ids)} configs (100%, warm-start, lastIter {LAST_ITER}):")
    for i in ids:
        print(f"  config_policy_{i}.xml -> output/runs_2026/policy_{i}_100pct/")


if __name__ == "__main__":
    main()
