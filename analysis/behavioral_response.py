#!/usr/bin/env python3
"""Agent-level behavioral response to charging surcharges — a simulation-only experiment.
Tracks the SAME agents from baseline into the policy scenarios and shows: (a) the near-flat
public-charging elasticity, (b) the per-agent change in public share (mostly zero), and
(c) who is captive — of baseline public chargers, how many still rely on public under +10c,
split by home-charger access. -> paper/figures/behavioral_response.png
Caveat: uses the flat-baseline-warm-started policy runs (to be refreshed with per-type runs)."""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
FIG = REPO / "paper/figures"; RUNS = ROOT / "scenarios/maryland/output/runs_2026"
hc = pd.read_parquet(REPO / "paper/tables/per_agent_homecharger.parquet").set_index("person_id")


def venue_share(run):
    f = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*charging_sessions.csv")),
               key=lambda p: int(p.split("it.")[1].split("/")[0]))[-1]
    d = pd.read_csv(f, sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
    g = d.groupby(["person_id", "charger_type_3way"]).e.sum().unstack(fill_value=0)
    for v in ["home", "work", "public"]:
        if v not in g: g[v] = 0.0
    g["pub_share"] = g["public"] / g[["home", "work", "public"]].sum(1).clip(lower=1e-9)
    return g


base = venue_share("baseline")
pol = {k: venue_share(r) for k, r in
       {"T1": "policy_T1_state_public_5c_100pct", "T2": "policy_T2_state_public_10c_100pct",
        "T3": "policy_T3_utility_evrider_3c_100pct", "T4": "policy_T4_combined_5c_2c_100pct"}.items()}

fig, ax = plt.subplots(1, 3, figsize=(13.5, 4.0))

# (a) aggregate public-energy share vs public surcharge (inelasticity)
def agg_pub(g): return g["public"].sum() / g[["home", "work", "public"]].sum().sum() * 100
xs = [0, 5, 10]; ys = [agg_pub(base), agg_pub(pol["T1"]), agg_pub(pol["T2"])]
ax[0].plot(xs, ys, marker="o", ms=7, color=pf.VERM, lw=2)
for x, y in zip(xs, ys): ax[0].annotate(f"{y:.1f}%", (x, y), textcoords="offset points", xytext=(6, 6), fontsize=9)
ax[0].set(xlabel="public-charging surcharge (¢/kWh)", ylabel="public share of energy (%)",
          title="(a) Charging is price-inelastic", ylim=(0, max(ys) * 1.6))
ax[0].grid(alpha=0.25)
ax[0].text(0.5, max(ys) * 1.35, "public share barely falls\neven at +10¢/kWh", fontsize=8.5, style="italic", color=pf.GREY)

# (b) per-agent change in public share, baseline -> T2 (+10c)
j = base[["pub_share"]].join(pol["T2"][["pub_share"]], lsuffix="_b", rsuffix="_p", how="inner")
dlt = (j.pub_share_p - j.pub_share_b) * 100
ax[1].hist(dlt, bins=np.arange(-100, 101, 5), color=pf.BLUE, edgecolor="white", lw=0.3)
ax[1].axvline(0, color="k", lw=0.8)
ax[1].set(xlabel="Δ public share, baseline → +10¢ (pp)", ylabel="number of agents",
          title="(b) Most agents do not change", yscale="log")
ax[1].text(0.03, 0.9, f"{(dlt.abs() < 2).mean()*100:.0f}% change < 2 pp", transform=ax[1].transAxes, fontsize=9)

# (c) captivity: of baseline public chargers, % still public under +10c, by home access
bp = base[base["public"] > 0].join(pol["T2"][["public"]].rename(columns={"public": "public_p"}), how="inner")
bp["still"] = bp["public_p"] > 0
bp["home_access"] = hc.reindex(bp.index)["has_home_charger"].map({True: "Has home\ncharger", False: "No home\ncharger"})
tab = bp.groupby("home_access").still.mean() * 100
ax[2].bar(range(len(tab)), tab.values, color=[pf.GREEN, pf.VERM], edgecolor="k", lw=0.3, width=0.6)
ax[2].set_xticks(range(len(tab))); ax[2].set_xticklabels(tab.index, fontsize=9)
for i, v in enumerate(tab.values): ax[2].text(i, v + 1, f"{v:.0f}%", ha="center", fontsize=10, fontweight="bold")
ax[2].set(ylabel="% still charging public at +10¢", title="(c) The captive are trapped", ylim=(0, 108))
ax[2].grid(axis="y", alpha=0.25)

fig.tight_layout()
fig.savefig(FIG / "behavioral_response.png", dpi=300, bbox_inches="tight")
fig.savefig(FIG / "behavioral_response.pdf", bbox_inches="tight")
plt.close(fig)
print("-> behavioral_response.png")
print(f"  public share: base {ys[0]:.1f}% -> +5¢ {ys[1]:.1f}% -> +10¢ {ys[2]:.1f}%")
print(f"  {(dlt.abs()<2).mean()*100:.0f}% of agents change public share <2pp under +10¢")
print("  still-public under +10¢:", dict(tab.round(0)))
