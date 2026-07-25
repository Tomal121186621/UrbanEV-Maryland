#!/usr/bin/env python3
"""
charging_profiles.py — WHO uses which charger type, WHERE they live, WHAT trip purpose
they charge at, and their trip/charging context. Connects charging behaviour to the
policy-incidence story (public-charging reliance = exposure to public surcharges).

From a run's charging_sessions.csv (+ ev_owners demographics) it profiles each charger
venue (home / work / public) by:
  - income octile, housing tenure (own/rent), dwelling type, BEV/PHEV, home-charger access
  - trip purpose (activity_type at which charging occurs)
  - home county / urban-rural
  - charging context: start-SOC, walk distance to charger, hour of day
Outputs figures -> <run>/charging_profiles/ and a who-uses-what table -> paper/tables/.
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
PAPER = REPO / "paper"
ACT = {1: "home", 2: "work", 3: "volunteer", 4: "school", 5: "shopping", 6: "meal_quick",
       7: "meal", 8: "gas", 9: "healthcare", 10: "errand", 11: "socialize", 12: "civic",
       13: "exercise", 14: "recreation", 15: "entertainment", 16: "dropoff", 18: "other"}
VEN = ["home", "work", "public"]
VCOL = {"home": pf.BLUE, "work": pf.GREEN, "public": pf.ORANGE}


def load(run_name="baseline"):
    cand = sorted(glob.glob(str(RUNS / f"{run_name}/ITERS/it.*/*.charging_sessions.csv")),
                  key=lambda s: int(s.split("it.")[1].split("/")[0]))
    d = pd.read_csv(cand[-1], sep=";")
    ev = pd.read_parquet(EVO)[["person_id", "home_county", "home_type", "home_ownership"]]
    d = d.merge(ev, left_on="person_id", right_on="person_id", how="left")
    d["ven"] = d.charger_type_3way
    d["has_home"] = pd.to_numeric(d.home_charger_power_kw, errors="coerce") > 0
    d["renter"] = pd.to_numeric(d.home_ownership, errors="coerce") == 2
    d["apt"] = pd.to_numeric(d.home_type, errors="coerce") >= 3
    d["oct"] = pd.qcut(pd.to_numeric(d.income_usd, errors="coerce").rank(method="first"), 8, labels=range(1, 9))
    d["purpose"] = d.activity_type.astype(str).str.replace(" charging.*", "", regex=True).str.strip()
    return d, cand[-1].split("it.")[1].split("/")[0]


def stacked_share(d, by, order, labels, name, title, xlabel, outdir):
    t = d.groupby([by, "ven"]).size().unstack(fill_value=0)
    t = t.div(t.sum(1), axis=0).reindex(order)
    fig, ax = pf.newfig(6.2, 3.8); bottom = np.zeros(len(order))
    for v in VEN:
        vals = t.get(v, pd.Series(0, index=order)).fillna(0).to_numpy()
        ax.bar(range(len(order)), vals, bottom=bottom, color=VCOL[v], label=v, edgecolor="k", lw=0.3)
        bottom += vals
    ax.set(xticks=range(len(order)), ylabel="share of charging sessions", title=title, xlabel=xlabel)
    ax.set_xticklabels(labels, rotation=20, ha="right"); pf.legout(ax)
    pf.save(fig, outdir, name)


def main():
    run = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    d, it = load(run)
    OUT = RUNS / run / "charging_profiles"
    print(f"[{run} it.{it}] {len(d):,} sessions | venue mix {d.ven.value_counts(normalize=True).round(3).to_dict()}")

    # 1. WHO — venue mix by income octile
    stacked_share(d, "oct", list(range(1, 9)), [str(i) for i in range(1, 9)],
                  "venue_by_income", "Charging venue by income octile", "income octile", OUT)
    # 2. WHO — by home-charger access (the key equity split)
    stacked_share(d, "has_home", [True, False], ["has home charger", "no home charger"],
                  "venue_by_homeaccess", "Charging venue by home-charger access", "", OUT)
    # 3. WHO — by tenure + dwelling
    d["tengrp"] = np.where(d.apt & d.renter, "apt renter",
                  np.where(d.apt, "apt owner", np.where(d.renter, "SF renter", "SF owner")))
    stacked_share(d, "tengrp", ["SF owner", "SF renter", "apt owner", "apt renter"],
                  ["SF owner", "SF renter", "apt owner", "apt renter"],
                  "venue_by_tenure", "Charging venue by dwelling × tenure", "", OUT)
    # 4. WHAT PURPOSE — activity types where charging occurs (non-home venues)
    pub = d[d.ven != "home"]
    pc = pub.purpose.map(lambda s: s if s in ["work", "shopping", "meal", "meal_quick", "errand",
                                              "recreation", "entertainment", "healthcare", "socialize"] else "other")
    vc = pc.value_counts(normalize=True).head(10)[::-1]
    fig, ax = pf.newfig(5.6, 4)
    ax.barh(vc.index, vc.values * 100, color=pf.ORANGE, edgecolor="k", lw=0.3)
    ax.set(xlabel="% of away-from-home charging sessions", title="Trip purpose at public/work charging")
    pf.save(fig, OUT, "purpose_of_charging")
    # 5. WHERE — public-charging reliance by home county (top/bottom)
    cty = d.assign(pub=d.ven == "public").groupby("home_county").pub.mean().sort_values()
    cty = pd.concat([cty.head(6), cty.tail(6)])
    fig, ax = pf.newfig(6, 4.2)
    ax.barh([str(int(c))[-3:] for c in cty.index], cty.values * 100, color=pf.PURPLE, edgecolor="k", lw=0.3)
    ax.set(xlabel="% of sessions at public chargers", title="Public-charging reliance by home county")
    pf.save(fig, OUT, "public_reliance_by_county")
    # 6. CONTEXT — start-SOC by venue
    fig, ax = pf.newfig(6, 3.6)
    for v in VEN:
        s = pd.to_numeric(d[d.ven == v].soc_start, errors="coerce").dropna()
        ax.hist(s, bins=np.linspace(0, 1, 21), histtype="step", lw=2, color=VCOL[v], label=v, density=True)
    ax.set(xlabel="state of charge at plug-in", ylabel="density", title="Start-SOC by charging venue"); pf.legout(ax)
    pf.save(fig, OUT, "start_soc_by_venue")

    # who-uses-what table
    tab = []
    for grp, lab in [("has_home", "home-charger access"), ("tengrp", "dwelling×tenure")]:
        t = d.groupby([grp, "ven"]).size().unstack(fill_value=0); t = (t.div(t.sum(1), axis=0) * 100).round(1)
        t.to_csv(PAPER / "tables" / f"who_uses_what_{grp}.csv")
    print(f"[done] 6 profile figures -> {OUT} ; who-uses-what tables -> paper/tables/")
    # headline equity link
    nh = d[~d.has_home]; print(f"  agents WITHOUT home charging: {nh.ven.value_counts(normalize=True).round(2).to_dict()}")


if __name__ == "__main__":
    main()
