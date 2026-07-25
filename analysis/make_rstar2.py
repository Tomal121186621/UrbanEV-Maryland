#!/usr/bin/env python3
"""Complete the shadow-gas-tax-gap (R*) analysis — all emergent/structural cuts.
  fig16_corridor_rstar : R* accrued on named corridors ($M) -> which specific roads leak
                         the gas tax (emergent from routing).
  fig17_who_drives_gap : R* by vehicle segment and by income decile + counterfactual-mpg
                         distribution -> who generates the gap.
  fig18_rstar_sensitivity : R* under alternative counterfactual-fuel-economy and gas-tax
                            assumptions -> robustness of the headline number.
-> paper/figures/trb/*.pdf|png"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
OUT = REPO / "paper/figures/trb"
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
RSTAR = 33.3; DAYS = 348; GASTAX = 0.466
BLU, ORA, GRN, VER, PUR, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.PURPLE, pf.GREY

pa = pd.read_csv(RUNS / "baseline/shadow_tax_gap_per_agent.csv")
pa["gap_yr"] = pa.state_tax_gap_day_usd * DAYS

# ============================================ FIG 16: corridor R*
def fig_corridor():
    lv = pd.read_parquet(RUNS / "baseline/route_analysis/link_vmt.parquet")
    cor = pd.read_parquet(RUNS / "baseline/route_analysis/link_corridor.parquet")
    j = lv.join(cor, how="inner"); tot = lv.vmt.sum()
    g = (j.groupby("corridor").vmt.sum() / tot * RSTAR).sort_values(ascending=False).head(10)[::-1]
    fig, ax = pf.newfig(6.8, 4.2)
    ax.barh(range(len(g)), g.values, color=VER, edgecolor="k", lw=0.4)
    ax.set_yticks(range(len(g))); ax.set_yticklabels(g.index, fontsize=9)
    for i, v in enumerate(g.values): ax.text(v + 0.03, i, f"${v:.1f}M", va="center", fontsize=8)
    ax.set(xlabel="shadow gas-tax gap accrued ($M/yr)",
           title="Which corridors leak the gas tax (top 10)")
    ax.grid(axis="x", alpha=0.25)
    pf.save(fig, OUT, "fig16_corridor_rstar")
    print(f"[16] corridor R*: top = {g.index[-1]} ${g.values[-1]:.1f}M")

# ============================================ FIG 17: who drives the gap
def fig_who():
    fig, ax = plt.subplots(1, 3, figsize=(12.6, 3.8))
    # (a) by vehicle segment (BEV/PHEV)
    seg = pa.groupby("ev_type").gap_yr.sum() / 1e6
    seg = seg.sort_values(ascending=False)
    ax[0].bar(range(len(seg)), seg.values, color=[BLU, ORA, GRN, PUR][:len(seg)], edgecolor="k", lw=0.4)
    ax[0].set_xticks(range(len(seg))); ax[0].set_xticklabels(seg.index, fontsize=9, rotation=15)
    for i, v in enumerate(seg.values): ax[0].text(i, v + 0.3, f"${v:.1f}M", ha="center", fontsize=8)
    ax[0].set(ylabel="R* contribution ($M/yr)", title="(a) Gap by powertrain", ylim=(0, seg.max()*1.2))
    # (b) MEAN gap per owner by income bracket (per-capita — isolates driving intensity;
    # bracket sizes are very unequal since EV ownership skews high-income, so totals would
    # just track owner counts. Per-owner is the honest cut.)
    d = pa.groupby("income_decile").gap_yr.mean()
    ax[1].bar(d.index, d.values, color=GRN, edgecolor="k", lw=0.4)
    ax[1].set(xlabel="income bracket (survey code, low→high)", ylabel="mean R* per owner ($/yr)",
              title="(b) Per-owner gap by income")
    ax[1].grid(axis="y", alpha=0.25)
    # (c) counterfactual mpg distribution (the key assumption)
    ax[2].hist(pa.mpg_counterfactual.dropna(), bins=30, color=GRY, edgecolor="white", lw=0.3)
    ax[2].axvline(pa.mpg_counterfactual.median(), color=VER, ls="--", lw=1,
                  label=f"median {pa.mpg_counterfactual.median():.0f} mpg")
    ax[2].set(xlabel="counterfactual fuel economy (mpg)", ylabel="EV owners",
              title="(c) Displaced-vehicle efficiency"); ax[2].legend(fontsize=8)
    for a in ax: a.grid(alpha=0.2)
    fig.suptitle("Who drives the shadow gas-tax gap", fontsize=12, fontweight="bold", y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT / "fig17_who_drives_gap.pdf"); fig.savefig(OUT / "fig17_who_drives_gap.png", dpi=300)
    plt.close(fig)
    top = pa.groupby("income_decile").gap_yr.sum();
    print(f'[17] gap by powertrain: {dict(seg.round(1))}; per-owner gap flat ~${pa.gap_yr.mean():.0f}/yr')

# ============================================ FIG 18: R* sensitivity
def fig_sensitivity():
    elec_vmt_yr = pa.daily_elec_vmt_mi.sum() * DAYS      # total electric VMT/yr
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.0))
    # (a) vs counterfactual mpg
    mpgs = np.arange(22, 41, 1)
    rr = elec_vmt_yr / mpgs * GASTAX / 1e6
    ax[0].plot(mpgs, rr, color=VER, lw=2.2)
    m0 = pa.mpg_counterfactual.median()
    ax[0].scatter([m0], [elec_vmt_yr / m0 * GASTAX / 1e6], color=BLU, s=60, zorder=5, edgecolor="k", lw=0.5)
    ax[0].annotate(f"baseline\n{m0:.0f} mpg → ${elec_vmt_yr/m0*GASTAX/1e6:.1f}M",
                   (m0, elec_vmt_yr/m0*GASTAX/1e6), xytext=(m0+2, elec_vmt_yr/m0*GASTAX/1e6+3),
                   fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[0].set(xlabel="assumed counterfactual mpg", ylabel="R* ($M/yr)",
              title="(a) Sensitivity to displaced fuel economy")
    ax[0].grid(alpha=0.25)
    # (b) vs gas tax rate (federal+state scenarios)
    rates = np.arange(0.25, 0.71, 0.02)
    rr2 = elec_vmt_yr / m0 * rates / 1e6
    ax[1].plot(rates * 100, rr2, color=GRN, lw=2.2)
    ax[1].scatter([GASTAX*100], [RSTAR], color=BLU, s=60, zorder=5, edgecolor="k", lw=0.5)
    ax[1].annotate(f"MD {GASTAX*100:.0f}¢/gal\n→ ${RSTAR:.0f}M", (GASTAX*100, RSTAR),
                   xytext=(GASTAX*100-16, RSTAR+3), fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=0.6))
    ax[1].set(xlabel="gas-tax rate (¢/gal)", ylabel="R* ($M/yr)",
              title="(b) Sensitivity to gas-tax rate")
    ax[1].grid(alpha=0.25)
    fig.suptitle("Robustness of the shadow gas-tax gap to its two key assumptions",
                 fontsize=12, fontweight="bold", y=1.0)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT / "fig18_rstar_sensitivity.pdf"); fig.savefig(OUT / "fig18_rstar_sensitivity.png", dpi=300)
    plt.close(fig)
    print(f"[18] R* sensitivity: {elec_vmt_yr/40*GASTAX/1e6:.1f}M (40mpg) to {elec_vmt_yr/22*GASTAX/1e6:.1f}M (22mpg)")

if __name__ == "__main__":
    fig_corridor(); fig_who(); fig_sensitivity()
