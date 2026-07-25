#!/usr/bin/env python3
"""
road_vmt_fee.py — design + evaluate a ROAD-CLASS-DIFFERENTIATED VMT fee for EVs that
recovers the shadow gas-tax gap R*. Charges EVs per-mile only on the road classes the
fuel tax funds (interstate, or interstate+arterial), at a rate sized to recover R*.

Computes PER-AGENT VMT by road class from the baseline link-traversal events
(congestion-independent), then evaluates each design on adequacy (= R* by construction),
Suits index, winners/losers vs the gas-tax-equivalent, and burden by income — and
compares to the flat RUC. Outputs -> paper/tables/ + paper/figures/.
"""
import sys, gzip, re
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
B = ROOT / "scenarios/maryland/output/runs_2026/baseline"
RC = REPO / "Input/network/link_road_class.parquet"
PA = B / "shadow_tax_gap_per_agent.csv"
PAPER = REPO / "paper"; DAYS = 348


def suits(inc, tax):
    o = np.argsort(inc); ct = np.concatenate([[0], np.cumsum(tax[o]) / tax[o].sum()])
    ci = np.concatenate([[0], np.cumsum(inc[o]) / inc[o].sum()])
    return float(1 - 2 * np.trapezoid(ct, ci))


def per_agent_roadclass_vmt():
    rc = pd.read_parquet(RC); length = rc.length_m.to_dict(); road = rc.road_class.to_dict()
    veh = defaultdict(lambda: defaultdict(float))
    lp = re.compile(r'link="([^"]+)"'); vp = re.compile(r'vehicle="([^"]+)"')
    print("[events] per-agent road-class VMT ...", flush=True)
    with gzip.open(B / "output_events.xml.gz", "rt") as f:
        for ln in f:
            if 'type="left link"' in ln:
                lk = lp.search(ln); vv = vp.search(ln)
                if lk and vv:
                    veh[vv.group(1)][road.get(lk.group(1), "other")] += length.get(lk.group(1), 0.0)
    rows = {v: {c: m / 1609.344 / 3 for c, m in cd.items()} for v, cd in veh.items()}   # mi/day
    return pd.DataFrame(rows).T.fillna(0)


def main():
    va = per_agent_roadclass_vmt()
    pa = pd.read_csv(PA).set_index("vehicle_id")
    df = pa.join(va, how="left").fillna(0)
    inc = df.income_usd.to_numpy(float)
    R = (df.state_tax_gap_day_usd * DAYS).sum()
    fair = (df.state_tax_gap_day_usd * DAYS).to_numpy(float)
    df["oct"] = pd.qcut(df.income_usd.rank(method="first"), 8, labels=range(1, 9))

    for c in ["interstate", "arterial", "collector", "local"]:
        if c not in df: df[c] = 0.0
    bases = {"flat_RUC": df[["interstate", "arterial", "collector", "local"]].sum(1),
             "interstate_only": df.interstate,
             "interstate+arterial": df.interstate + df.arterial}
    rows = []
    inst = {}
    for name, vmt in bases.items():
        rate = R / (vmt.sum() * DAYS)                       # $/mi to recover R*
        b = (vmt * DAYS * rate).to_numpy(float)
        inst[name] = b
        rows.append(dict(instrument=name, rate_c_per_mi=round(rate * 100, 3),
                         revenue_Myr=round(b.sum() / 1e6, 1), suits=round(suits(inc, b), 3),
                         winners_pct=round((b < fair - 1).mean() * 100, 1),
                         losers_pct=round((b > fair + 1).mean() * 100, 1),
                         mean_yr=round(b.mean(), 1)))
    summ = pd.DataFrame(rows)
    summ.to_csv(PAPER / "tables/road_vmt_fee.csv", index=False)
    print(summ.to_string(index=False))

    # burden by income octile
    fig, ax = pf.newfig(6.6, 3.8)
    for name, b in inst.items():
        m = pd.Series(b).groupby(df.oct.values).mean()
        ax.plot(range(1, 9), m.values, marker="o", label=f"{name} ({summ.set_index('instrument').loc[name,'rate_c_per_mi']:.1f}c/mi)")
    ax.set(xlabel="income octile (low→high)", ylabel="mean fee ($/yr)",
           title="Road-class VMT fee burden by income (each recovers R*)")
    pf.legout(ax); pf.save(fig, PAPER / "figures", "road_vmt_fee_by_income")
    print(f"[done] road-class VMT fee designs -> paper/tables/road_vmt_fee.csv (R*=${R/1e6:.1f}M)")


if __name__ == "__main__":
    main()
