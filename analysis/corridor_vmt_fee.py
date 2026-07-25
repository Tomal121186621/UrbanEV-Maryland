#!/usr/bin/env python3
"""
corridor_vmt_fee.py — design + evaluate CORRIDOR-SPECIFIC VMT fees for EVs. Charges EVs
per-mile only on selected named corridors (I-95, the beltways, all major interstates,
or all limited-access corridors), each rate sized to recover R*. Computes per-agent VMT
by corridor from the baseline events (congestion-independent) and evaluates each design
on adequacy, rate, Suits index, winners/losers, and burden by income.
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
OUT = B / "route_analysis"; PAPER = REPO / "paper"; DAYS = 348
CORR = pd.read_parquet(OUT / "link_corridor.parquet").corridor.to_dict()
LEN = pd.read_parquet(REPO / "Input/network/link_road_class.parquet").length_m.to_dict()

SCEN = {
    "I-95 corridor": ["I-95"],
    "Beltways (I-495+I-695)": ["I-495 (Capital Beltway)", "I-695 (Baltimore Beltway)"],
    "Major interstates": ["I-95", "I-270", "I-495 (Capital Beltway)", "I-695 (Baltimore Beltway)",
                          "I-97", "I-70", "I-83", "I-895"],
    "All corridors": None,      # every labelled corridor
}


def suits(inc, tax):
    o = np.argsort(inc); ct = np.concatenate([[0], np.cumsum(tax[o]) / tax[o].sum()])
    ci = np.concatenate([[0], np.cumsum(inc[o]) / inc[o].sum()])
    return float(1 - 2 * np.trapezoid(ct, ci))


def per_agent_corridor_vmt():
    veh = defaultdict(lambda: defaultdict(float))
    lp = re.compile(r'link="([^"]+)"'); vp = re.compile(r'vehicle="([^"]+)"')
    print("[events] per-agent corridor VMT ...", flush=True)
    with gzip.open(B / "output_events.xml.gz", "rt") as f:
        for ln in f:
            if 'type="left link"' in ln:
                lk = lp.search(ln); vv = vp.search(ln)
                if lk and vv:
                    c = CORR.get(lk.group(1))
                    if c:
                        veh[vv.group(1)][c] += LEN.get(lk.group(1), 0.0)
    return pd.DataFrame({v: {c: m / 1609.344 / 3 for c, m in cd.items()} for v, cd in veh.items()}).T.fillna(0)


def main():
    va = per_agent_corridor_vmt()
    pa = pd.read_csv(B / "shadow_tax_gap_per_agent.csv").set_index("vehicle_id")
    df = pa.join(va, how="left").fillna(0)
    inc = df.income_usd.to_numpy(float)
    R = (df.state_tax_gap_day_usd * DAYS).sum()
    fair = (df.state_tax_gap_day_usd * DAYS).to_numpy(float)
    df["oct"] = pd.qcut(df.income_usd.rank(method="first"), 8, labels=range(1, 9))
    cols = [c for c in va.columns]

    rows = []; inst = {}
    for name, corrs in SCEN.items():
        use = cols if corrs is None else [c for c in corrs if c in df]
        vmt = df[use].sum(1)
        if vmt.sum() == 0:
            continue
        rate = R / (vmt.sum() * DAYS)
        b = (vmt * DAYS * rate).to_numpy(float)
        inst[name] = b
        rows.append(dict(scenario=name, rate_c_per_mi=round(rate * 100, 2),
                         payers_pct=round((vmt > 0).mean() * 100, 1),
                         revenue_Myr=round(b.sum() / 1e6, 1), suits=round(suits(inc, b), 3),
                         winners_pct=round((b < fair - 1).mean() * 100, 1),
                         losers_pct=round((b > fair + 1).mean() * 100, 1)))
    summ = pd.DataFrame(rows)
    summ.to_csv(PAPER / "tables/corridor_vmt_fee.csv", index=False)
    print(summ.to_string(index=False))

    fig, ax = pf.newfig(6.6, 3.8)
    for name, b in inst.items():
        m = pd.Series(b).groupby(df.oct.values).mean()
        ax.plot(range(1, 9), m.values, marker="o", label=name)
    ax.set(xlabel="income octile (low→high)", ylabel="mean fee ($/yr)",
           title="Corridor VMT-fee burden by income (each recovers R*)")
    pf.legout(ax); pf.save(fig, PAPER / "figures", "corridor_fee_by_income")
    print(f"[done] corridor fee designs -> paper/tables/corridor_vmt_fee.csv")


if __name__ == "__main__":
    main()
