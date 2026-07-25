#!/usr/bin/env python3
"""Additional relevant analysis figures (uniform pubfig style):
  1. equity_incidence.png  — 2x2: effective tax rate by income, Lorenz/concentration curves,
     winners vs losers, mean burden by income octile (per-agent burdens).
  2. charger_composition.png — charger-type shares (sessions & energy) from baseline sessions.
Congestion-independent. -> paper/figures/.
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
T = REPO / "paper/tables"; FIG = REPO / "paper/figures"
d = pd.read_parquet(T / "per_agent_burdens.parquet")
inc = d.income_usd.to_numpy(float); o = np.argsort(inc)
pc = pd.read_csv(T / "policy_comparison.csv").set_index("instrument")

INST = [("gas_equiv", "Gas-tax equivalent", pf.GREY, "-"),
        ("ruc", "Flat RUC (per-mile)", pf.GREEN, "-"),
        ("md_actual", "MD fee (\\$125/\\$100)", pf.ORANGE, "-"),
        ("flat_fee", "Flat fee (\\$224)", pf.VERM, "--"),
        ("T3_utility_evrider_3c", "Charging: home +3¢", pf.BLUE, ":")]

# =====================================================================
# FIG 1 — equity / incidence panel (2x2)
fig, ax = plt.subplots(2, 2, figsize=(9.6, 7.2)); ax = ax.ravel()

# (a) effective tax rate by income octile  (burden / income, %)
for k, lab, c, ls in INST:
    er = d.groupby("oct")[k].sum() / d.groupby("oct").income_usd.sum() * 100
    ax[0].plot(range(1, 9), er.values, marker="o", ms=4, color=c, ls=ls, label=lab)
ax[0].set(xlabel="income octile (low → high)", ylabel="effective rate (% of income)",
          title="(a) Effective tax rate by income")
ax[0].grid(alpha=0.25)

# (b) concentration (Lorenz-type) curves: cumulative tax vs cumulative income
ci = np.concatenate([[0], np.cumsum(inc[o]) / inc[o].sum()])
ax[1].plot([0, 1], [0, 1], color="k", lw=0.8, ls="--", label="proportional")
for k, lab, c, ls in INST:
    b = d[k].to_numpy(float)
    ct = np.concatenate([[0], np.cumsum(b[o]) / b.sum()])
    ax[1].plot(ci, ct, color=c, ls=ls, lw=1.8)
ax[1].set(xlabel="cumulative share of income", ylabel="cumulative share of tax",
          title="(b) Tax concentration curves")
ax[1].grid(alpha=0.25)

# (c) winners vs losers vs the gas-tax-equivalent fair share
order = ["ruc", "flat_fee", "md_actual", "T3_utility_evrider_3c", "T1_state_public_5c"]
lab_c = {"ruc": "Flat RUC", "flat_fee": "Flat fee", "md_actual": "MD fee",
         "T3_utility_evrider_3c": "Charge home+3¢", "T1_state_public_5c": "Charge pub+5¢"}
x = np.arange(len(order))
ax[2].bar(x, [pc.loc[k, "winners_pct"] for k in order], color=pf.GREEN, edgecolor="k", lw=0.3, label="winners")
ax[2].bar(x, [-pc.loc[k, "losers_pct"] for k in order], color=pf.VERM, edgecolor="k", lw=0.3, label="losers")
ax[2].axhline(0, color="k", lw=0.7)
ax[2].set_xticks(x); ax[2].set_xticklabels([lab_c[k] for k in order], rotation=25, ha="right", fontsize=8)
ax[2].set(ylabel="% of EV owners", title="(c) Winners vs losers vs. fuel tax")
ax[2].legend(fontsize=8, frameon=False)

# (d) mean annual burden by income octile
for k, lab, c, ls in INST:
    m = d.groupby("oct")[k].mean()
    ax[3].plot(range(1, 9), m.values, marker="o", ms=4, color=c, ls=ls)
ax[3].set(xlabel="income octile (low → high)", ylabel="mean burden (\\$/yr)",
          title="(d) Mean burden by income")
ax[3].grid(alpha=0.25)

# shared legend (from panel a lines) below
h, l = ax[0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=5, fontsize=8.5, frameon=False, bbox_to_anchor=(0.5, -0.02))
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(FIG / "equity_incidence.png", dpi=300, bbox_inches="tight")
fig.savefig(FIG / "equity_incidence.pdf", bbox_inches="tight")
plt.close(fig); print("-> equity_incidence.png")

# =====================================================================
# FIG 2 — charger-type composition (sessions & energy)
f = sorted(glob.glob(str(ROOT / "scenarios/maryland/output/runs_2026/baseline/ITERS/it.*/*charging_sessions.csv")),
           key=lambda p: int(p.split("it.")[1].split("/")[0]))[-1]
s = pd.read_csv(f, sep=";"); s["e"] = pd.to_numeric(s.energy_kwh, errors="coerce")
order5 = ["home", "work", "L2", "DCFC", "DCFC_TESLA"]
labs = ["Home", "Workplace", "Public L2", "Public DCFC", "DCFC-Tesla"]
cols = [pf.BLUE, pf.GREEN, pf.ORANGE, pf.VERM, pf.PURPLE]
sess = (s.charger_type.value_counts(normalize=True) * 100).reindex(order5).fillna(0)
ener = (s.groupby("charger_type").e.sum() / s.e.sum() * 100).reindex(order5).fillna(0)
fig, axc = pf.newfig(6.6, 3.8)
x = np.arange(len(order5)); w = 0.38
axc.bar(x - w / 2, sess.values, w, color=pf.BLUE, edgecolor="k", lw=0.3, label="% of sessions")
axc.bar(x + w / 2, ener.values, w, color=pf.ORANGE, edgecolor="k", lw=0.3, label="% of energy")
for i, (a, b) in enumerate(zip(sess.values, ener.values)):
    axc.text(i - w / 2, a + 1, f"{a:.0f}", ha="center", fontsize=7.5)
    axc.text(i + w / 2, b + 1, f"{b:.0f}", ha="center", fontsize=7.5)
axc.set_xticks(x); axc.set_xticklabels(labs, fontsize=9)
axc.set(ylabel="share (%)", title="Charging composition by charger type")
axc.legend(fontsize=8.5, frameon=False)
pf.save(fig, FIG, "charger_composition")
print("-> charger_composition.png")
print(f"[done] session source it.{f.split('it.')[1].split('/')[0]}; charger sessions%: " +
      ", ".join(f"{l} {v:.0f}" for l, v in zip(labs, sess.values)))
