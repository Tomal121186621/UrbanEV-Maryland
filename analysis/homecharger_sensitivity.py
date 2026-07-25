#!/usr/bin/env python3
"""ROBUSTNESS #1 — sensitivity of the policy conclusions to the assumed home-charger rate.
The home-charger rate (baseline 91.8%, assigned from NREL-278 x Ge-2021) is an INPUT, yet
it drives the home-vs-public inelasticity contrast and the equity story. Here we bound how
the conclusions move as the rate varies 80-95%.

Model (analytic, no re-sim): at a lower home-charger rate, the marginal agents who lose
home access shift their HOME charging energy to PUBLIC (they must charge somewhere and have
no home option). We reassign the lowest-propensity home owners first (by income, since the
NREL/Ge model gives higher-income/single-family owners home chargers first). Recompute:
  - home & public energy base (GWh)
  - home-surcharge rate that reaches R* (does it stay ~feasible?)
  - public-surcharge adequacy at a fixed 10c
  - Suits index of a public surcharge (does it stay regressive?)
-> paper/tables/homecharger_sensitivity.csv + paper/figures/trb/fig19_homecharger_sensitivity.png"""
import sys, glob, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
OUT = REPO / "paper/figures/trb"; TAB = REPO / "paper/tables"
DAYS, PLAN, RSTAR = 348.0, 3.0, 33.3
BLU, ORA, GRN, VER, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.GREY

# ---- per-agent charging energy by venue (converged baseline) ----
f = sorted(glob.glob(str(RUNS/"baseline_pertype/ITERS/it.*/*.charging_sessions.csv")),
           key=lambda p:int(p.split("it.")[1].split("/")[0]))[-1]
s = pd.read_csv(f, sep=";"); s["e"] = pd.to_numeric(s.energy_kwh, errors="coerce")
pae = s.groupby(["person_id","charger_type_3way"]).e.sum().unstack(fill_value=0)
for v in ["home","work","public"]:
    if v not in pae: pae[v]=0.0
pae = pae.reset_index()

# ---- join home-charger status + income ----
hc = pd.read_parquet(REPO/"paper/tables/per_agent_homecharger.parquet")[["person_id","has_home_charger"]]
ev = pd.read_parquet(REPO/"pipeline/data/interim/ev_owners.parquet")[["person_id","income"]]
d = pae.merge(hc, on="person_id", how="left").merge(ev, on="person_id", how="left")
d["has_home_charger"] = d.has_home_charger.fillna(True)
base_rate = d.has_home_charger.mean()

def suits(inc, tax):
    m = tax > 0
    if m.sum() < 2: return np.nan
    inc, tax = inc[m], tax[m]
    o = np.argsort(inc); ct = np.concatenate([[0], np.cumsum(tax[o])/tax[o].sum()])
    ci = np.concatenate([[0], np.cumsum(inc[o])/inc[o].sum()])
    return float(1 - 2*np.trapezoid(ct, ci))

ann = DAYS/PLAN/1e6      # kWh(3-day) -> GWh/yr
rows = []
for target in [0.80, 0.85, 0.90, base_rate, 0.95]:
    d2 = d.copy()
    # among current home owners, drop the LOWEST-income first until rate hits target
    if target < base_rate:
        owners = d2[d2.has_home_charger].sort_values("income")   # low income lose first
        n_drop = int(round((base_rate - target) * len(d2)))
        drop_ids = set(owners.person_id.iloc[:n_drop])
        lose = d2.person_id.isin(drop_ids)
        d2.loc[lose, "public"] += d2.loc[lose, "home"]           # home energy -> public
        d2.loc[lose, "home"] = 0.0
        d2.loc[lose, "has_home_charger"] = False
    elif target > base_rate:
        # add home chargers to highest-income captives; shift their public->home
        cap = d2[~d2.has_home_charger].sort_values("income", ascending=False)
        n_add = int(round((target - base_rate) * len(d2)))
        add_ids = set(cap.person_id.iloc[:n_add])
        gain = d2.person_id.isin(add_ids)
        d2.loc[gain, "home"] += d2.loc[gain, "public"]
        d2.loc[gain, "public"] = 0.0
        d2.loc[gain, "has_home_charger"] = True
    home_gwh = d2.home.sum()*ann; pub_gwh = d2.public.sum()*ann
    inc = d2.income.to_numpy(float)
    pub_burden = d2.public.values*ann*1e6*0.10                    # $ at +10c public
    home_rate_star = RSTAR/home_gwh*100 if home_gwh>0 else np.nan  # c/kWh to reach R*
    rows.append(dict(home_rate=round(d2.has_home_charger.mean()*100,1),
                     home_gwh=round(home_gwh,1), public_gwh=round(pub_gwh,1),
                     home_c_for_Rstar=round(home_rate_star,1),
                     public_10c_pct=round(pub_gwh*0.10/RSTAR*100,1),
                     suits_public10c=round(suits(inc, pub_burden),3)))
r = pd.DataFrame(rows).drop_duplicates("home_rate").sort_values("home_rate")
TAB.mkdir(parents=True, exist_ok=True); r.to_csv(TAB/"homecharger_sensitivity.csv", index=False)
print(r.to_string(index=False))

# ---- figure ----
fig, ax = plt.subplots(1, 3, figsize=(12.6, 3.7))
ax[0].plot(r.home_rate, r.home_c_for_Rstar, "-o", color=BLU, ms=6)
ax[0].axhline(0, color="k", lw=0.5)
ax[0].set(xlabel="assumed home-charger rate (%)", ylabel="home surcharge to reach $R^*$ (¢/kWh)",
          title="(a) Home-surcharge rate for full recovery")
ax[1].plot(r.home_rate, r.public_10c_pct, "-s", color=ORA, ms=6)
ax[1].set(xlabel="assumed home-charger rate (%)", ylabel="public +10¢ recovers (% of $R^*$)",
          title="(b) Public-surcharge adequacy")
ax[2].plot(r.home_rate, r.suits_public10c, "-^", color=VER, ms=6)
ax[2].axhline(0, color="k", lw=0.5, ls=":")
ax[2].set(xlabel="assumed home-charger rate (%)", ylabel="Suits index of public +10¢",
          title="(c) Public-surcharge regressivity")
for a in ax:
    a.grid(alpha=0.25); a.axvline(base_rate*100, color=GRY, ls=":", lw=1)
fig.suptitle("Robustness to the assumed home-charger rate: conclusions hold across 80–95%",
             fontsize=12, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0,0,1,0.95))
fig.savefig(OUT/"fig19_homecharger_sensitivity.pdf"); fig.savefig(OUT/"fig19_homecharger_sensitivity.png", dpi=300)
plt.close(fig)
print("\n-> fig19_homecharger_sensitivity + homecharger_sensitivity.csv")
