#!/usr/bin/env python3
"""Price-sweep Laffer analysis for publication. Two figures:
  laffer_public.png -- annual revenue vs PUBLIC surcharge, broken down by charger type
                       (L2 / DCFC / DCFC-Tesla), with R* line and the revenue PEAK marked
                       (where raising the price stops adding revenue -> the base evaporates).
  laffer_home.png   -- annual revenue vs HOME surcharge (inelastic base; can it reach R*?).
Revenue at a surcharge rate = (converged post-behaviour energy at that venue/type) x rate.
Because each scenario RE-SIMULATES, the energy base itself responds to the price.
-> paper/figures/laffer_public.png, laffer_home.png ; paper/tables/price_sweep.csv
Safe to run mid-sweep: plots whatever scenarios have finished."""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
FIG = REPO / "paper/figures"; TAB = REPO / "paper/tables"
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
DAYS = 348.0; PLAN = 3.0                  # 72-h plan -> annual
RSTAR = 33.3                              # $M/yr shadow gas-tax gap
PUB_TYPES = ["L2", "DCFC", "DCFC_TESLA"]  # the surcharged public charger types

PUB = [10, 25, 50, 100, 150, 200]         # public surcharge points (cents/kWh)
HOME = [10, 22, 40]                        # home surcharge points (cents/kWh)


def latest(run, require_converged=True):
    # only use CONVERGED runs (output_plans written) -> excludes non-settled energy bases
    if require_converged and not (RUNS / run / "output_plans.xml.gz").exists():
        return None
    fs = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    if not fs:
        return None
    d = pd.read_csv(fs[-1], sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
    return d


def energy_gwh(d, charger_types):
    """annual GWh charged at the given charger_type(s)."""
    return d[d.charger_type.isin(charger_types)].e.sum() / PLAN * DAYS / 1e6


def home_gwh(d):
    return d[d.charger_type == "home"].e.sum() / PLAN * DAYS / 1e6


# ---------- collect ----------
base = latest("baseline_pertype")
rows = []
if base is not None:
    rows.append(dict(family="public", cents=0, **{f"E_{t}": energy_gwh(base, [t]) for t in PUB_TYPES}))
    rows.append(dict(family="home", cents=0, E_home=home_gwh(base)))
for c in PUB:
    d = latest(f"sweep_pub_{c}c")
    if d is None: continue
    rows.append(dict(family="public", cents=c, **{f"E_{t}": energy_gwh(d, [t]) for t in PUB_TYPES}))
for c in HOME:
    d = latest(f"sweep_home_{c}c")
    if d is None: continue
    rows.append(dict(family="home", cents=c, E_home=home_gwh(d)))
df = pd.DataFrame(rows)

# ---------- revenue = energy(GWh)*1e6 kWh * (cents/100) $/kWh / 1e6 = $M ----------
# revenue($M) = E(GWh)*1e6 kWh/GWh * (cents/100 $/kWh) / 1e6 = E(GWh) * cents/100
pub = df[df.family == "public"].sort_values("cents").copy()
for t in PUB_TYPES:
    pub[f"rev_{t}"] = pub[f"E_{t}"] * (pub.cents / 100)             # $M
pub["rev_total"] = pub[[f"rev_{t}" for t in PUB_TYPES]].sum(axis=1)
home = df[df.family == "home"].sort_values("cents").copy()
home["rev_home"] = home["E_home"] * (home.cents / 100)

TAB.mkdir(parents=True, exist_ok=True)
out = pd.concat([pub, home], ignore_index=True)
out.to_csv(TAB / "price_sweep.csv", index=False)
print(pub[["cents", "E_L2", "E_DCFC", "E_DCFC_TESLA", "rev_L2", "rev_DCFC", "rev_total"]].round(2).to_string(index=False))
print()
print(home[["cents", "E_home", "rev_home"]].round(2).to_string(index=False))

CBLU, CORA, CGRN, CVER, CGRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.GREY

# ---------- FIG 1: PUBLIC Laffer curve, broken down by charger type ----------
if len(pub) >= 2:
    fig, ax = pf.newfig(6.6, 4.2)
    ax.axhline(RSTAR, color="k", ls="--", lw=1.1, label=f"$R^*$ = \\${RSTAR:.0f}M (full gap)")
    ax.plot(pub.cents, pub.rev_total, "-o", color=CVER, ms=6, lw=2.2, label="total public revenue", zorder=5)
    ax.plot(pub.cents, pub.rev_L2, "-s", color=CBLU, ms=5, lw=1.6, label="from L2")
    ax.plot(pub.cents, pub.rev_DCFC, "-^", color=CORA, ms=5, lw=1.6, label="from DCFC")
    ax.plot(pub.cents, pub.rev_DCFC_TESLA, "-D", color=CGRN, ms=4, lw=1.3, label="from DCFC-Tesla")
    # detect a TRUE peak (revenue turns over) vs still-rising
    if len(pub) >= 3:
        imax = pub.rev_total.values.argmax()
        pk = pub.iloc[imax]
        turned = imax < len(pub) - 1                      # max is not the last point -> reverted
        lbl = (f"peak ${pk.rev_total:.1f}M @ {pk.cents:.0f}¢ ({pk.rev_total/RSTAR*100:.0f}% of $R^*$)"
               if turned else
               f"still rising: ${pk.rev_total:.1f}M @ {pk.cents:.0f}¢\n({pk.rev_total/RSTAR*100:.0f}% of $R^*$ — base only −{(1-pub[['E_L2','E_DCFC','E_DCFC_TESLA']].iloc[imax].sum()/pub[['E_L2','E_DCFC','E_DCFC_TESLA']].iloc[0].sum())*100:.0f}%)")
        ax.annotate(lbl, (pk.cents, pk.rev_total), xytext=(pk.cents*0.30, pk.rev_total + RSTAR*0.10),
                    fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.7))
    ax.set(xlabel="public charging surcharge (¢/kWh)", ylabel="annual revenue ($M)",
           title="Public-charging surcharge: revenue vs. price")
    pf.legout(ax); pf.save(fig, FIG, "laffer_public")
    print(f"\n-> laffer_public.png  (peak {pub.rev_total.max():.1f}M = {pub.rev_total.max()/RSTAR*100:.0f}% of R*)")
else:
    print(f"\n[wait] public sweep has {len(pub)} point(s); need >=2 (>=3 to show the peak).")

# ---------- FIG 2: HOME Laffer curve ----------
if len(home) >= 2:
    fig, ax = pf.newfig(6.0, 4.2)
    ax.axhline(RSTAR, color="k", ls="--", lw=1.1, label=f"$R^*$ = \\${RSTAR:.0f}M (full gap)")
    ax.plot(home.cents, home.rev_home, "-o", color=CBLU, ms=6, lw=2.2, label="home surcharge revenue")
    # rate that would reach R* if perfectly inelastic (reference)
    if (home.E_home > 0).any():
        e0 = home.E_home.iloc[0] if home.cents.iloc[0] == 0 else home.E_home.mean()
        rate_star = RSTAR / e0 * 100                                # cents to reach R* if inelastic
        ax.axvline(rate_star, color=CGRY, ls=":", lw=1, label=f"reaches $R^*$ if inelastic ($\\approx${rate_star:.0f}¢)")
    ax.set(xlabel="home charging surcharge (¢/kWh)", ylabel="annual revenue ($M)",
           title="Home-charging surcharge: revenue vs. price")
    pf.legout(ax); pf.save(fig, FIG, "laffer_home")
    print(f"-> laffer_home.png  (max {home.rev_home.max():.1f}M = {home.rev_home.max()/RSTAR*100:.0f}% of R*)")
else:
    print(f"[wait] home sweep has {len(home)} point(s); need >=2.")
