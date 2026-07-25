#!/usr/bin/env python3
"""
paper_result_figs.py — Tier-1 result figures for the TRB paper:
  (1) recovery waterfall: R* -> minus MD fee -> residual, with charging surcharges;
  (2) rate-revenue adequacy frontier: surcharge revenue vs rate for home/public/all,
      with R* and residual reference lines (shows the rate each would need);
  (3) taxable-base decomposition: charging energy by venue (home mostly untaxable);
  (4) effective tax rate by income octile (regressivity of flat/registration vs gas-equiv).
Congestion-independent; uses baseline sessions + per-agent shadow-gap table. -> paper/figures/.
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
B = ROOT / "scenarios/maryland/output/runs_2026/baseline"
FIG = REPO / "paper/figures"; DAYS = 348
RSTAR = 33.3; MD_REV = 17.6; RESID = RSTAR - MD_REV     # $M/yr

# ---- baseline charging energy by venue (3-day sessions -> annual GWh) ----
sess = sorted(glob.glob(str(B / "ITERS/it.*/*.charging_sessions.csv")),
              key=lambda p: int(p.split("it.")[1].split("/")[0]))[-1]
d = pd.read_csv(sess, sep=";")
d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
E = d.groupby("charger_type_3way").e.sum() / 3 * DAYS / 1e6      # GWh/yr by venue
Ehome, Epub, Ework = E.get("home", 0), E.get("public", 0), E.get("work", 0)

# =====================================================================
# (1) Recovery waterfall
fig, ax = pf.newfig(6.6, 4.0)
steps = [("Shadow gap\n$R^*$", RSTAR, pf.GREY),
         ("$-$ MD fee\n(\$125/\$100)", -MD_REV, pf.ORANGE),
         ("Residual\ngap", RESID, pf.VERM)]
run = 0
for i, (lab, val, c) in enumerate(steps):
    if lab.startswith("Residual"):
        ax.bar(i, RESID, color=c, edgecolor="k", lw=0.4)
    elif val > 0:
        ax.bar(i, val, color=c, edgecolor="k", lw=0.4); run = val
    else:
        ax.bar(i, -val, bottom=run + val, color=c, edgecolor="k", lw=0.4); run += val
    ax.text(i, max(RSTAR, run) + 0.6, f"\${abs(val):.1f}M", ha="center", fontsize=9, fontweight="bold")
# charging surcharge markers
for r, lab in [(1.4, "T1"), (2.7, "T2"), (6.2, "T3"), (5.5, "T4")]:
    ax.plot([2], [r], "o", color=pf.BLUE, ms=5)
ax.text(2.32, 4.5, "charging\nsurcharges\n(T1–T4)", fontsize=7.5, color=pf.BLUE, va="center")
ax.set_xticks(range(3)); ax.set_xticklabels([s[0] for s in steps])
ax.set_ylabel("$ million / year"); ax.set_title("Recovering the shadow gas-tax gap")
ax.axhline(RESID, color=pf.VERM, lw=0.7, ls=":")
pf.save(fig, FIG, "recovery_waterfall")

# =====================================================================
# (2) Rate-revenue adequacy frontier
fig, ax = pf.newfig(6.6, 4.0)
rates = np.linspace(0, 0.30, 100)                        # $/kWh surcharge
ax.plot(rates * 100, rates * Ehome, color=pf.ORANGE, label=f"home only ({Ehome:.0f} GWh/yr)")
ax.plot(rates * 100, rates * Epub, color=pf.VERM, label=f"public only ({Epub:.0f} GWh/yr)")
ax.plot(rates * 100, rates * (Ehome + Epub + Ework), color=pf.GREEN,
        label=f"all charging ({Ehome+Epub+Ework:.0f} GWh/yr)")
ax.axhline(RSTAR, color="k", lw=0.9, ls="--"); ax.text(0.3, RSTAR + 0.6, "$R^*$ = \$33.3M", fontsize=8)
ax.axhline(RESID, color=pf.GREY, lw=0.9, ls=":"); ax.text(0.3, RESID + 0.6, "residual \$15.7M", fontsize=8)
# mark modeled surcharges
for x, y, t in [(5, 0.05 * Epub, "T1"), (10, 0.10 * Epub, "T2"), (3, 0.03 * Ehome, "T3")]:
    ax.plot(x, y, "ko", ms=4); ax.text(x + 0.3, y, t, fontsize=7.5)
ax.set_xlabel("surcharge rate (¢/kWh)"); ax.set_ylabel("annual revenue ($ million)")
ax.set_title("Charging-surcharge revenue vs. rate (inelastic base)")
ax.set_ylim(0, RSTAR * 1.4); pf.legout(ax); pf.save(fig, FIG, "rate_revenue_frontier")

# =====================================================================
# (3) Taxable-base decomposition
fig, ax = pf.newfig(5.6, 3.8)
vals = [Ehome, Ework, Epub]; labs = ["Home\n(residential meter,\nuntaxable)", "Workplace", "Public\n(taxable)"]
cols = [pf.GREY, pf.BLUE, pf.GREEN]
bars = ax.bar(range(3), vals, color=cols, edgecolor="k", lw=0.4)
tot = sum(vals)
for i, v in enumerate(vals):
    ax.text(i, v + tot * 0.01, f"{v:.0f} GWh\n({v/tot*100:.0f}%)", ha="center", fontsize=8.5, fontweight="bold")
ax.set_xticks(range(3)); ax.set_xticklabels(labs, fontsize=8)
ax.set_ylabel("annual charging energy (GWh)")
ax.set_title("Charging energy base: the taxable share is small")
pf.save(fig, FIG, "taxable_base")

# =====================================================================
# (4) Effective tax rate by income octile
pa = pd.read_csv(B / "shadow_tax_gap_per_agent.csv")
ev = pd.read_parquet(ROOT.parent / "pipeline/data/interim/ev_owners.parquet")[["person_id", "ev_powertrain"]]
pa = pa.merge(ev, left_on="vehicle_id", right_on="person_id", how="left")
pa["inc"] = pa.income_usd
pa["oct"] = pd.qcut(pa.inc.rank(method="first"), 8, labels=range(1, 9))
pa["gas_equiv"] = pa.state_tax_gap_day_usd * DAYS
pa["md_fee"] = np.where(pa.ev_powertrain == "BEV", 125.0, 100.0)
pa["flat_fee"] = pa.gas_equiv.sum() / len(pa)
fig, ax = pf.newfig(6.6, 4.0)
for col, c, lab in [("gas_equiv", pf.GREY, "Gas-tax equivalent"),
                    ("flat_fee", pf.ORANGE, "Flat fee (\$224)"),
                    ("md_fee", pf.VERM, "MD fee (\$125/\$100)")]:
    er = (pa.groupby("oct")[col].sum() / pa.groupby("oct").inc.sum() * 100)
    ax.plot(range(1, 9), er.values, marker="o", color=c, label=lab)
ax.set_xlabel("income octile (low → high)"); ax.set_ylabel("effective rate (% of income)")
ax.set_title("Flat and registration fees are regressive")
pf.legout(ax); pf.save(fig, FIG, "effective_tax_rate")

print(f"[done] 4 result figures -> {FIG}")
print(f"  energy GWh/yr: home {Ehome:.0f}, public {Epub:.0f}, work {Ework:.0f}")
print(f"  public surcharge to close residual: {RESID/Epub*100:.1f} c/kWh; home: {RESID/Ehome*100:.1f} c/kWh")
