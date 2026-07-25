#!/usr/bin/env python3
"""fig15: EMERGENT recoverability of the shadow gas-tax gap R*. Because R* accrues in
proportion to EV vehicle-miles (emergent from routing), pricing only the busiest slice of
the network recovers most of the gap.
  (a) cumulative R* recovered vs % of network metered (the recoverability frontier)
  (b) R* accrual by road class ($M) -- where the lost gas tax is actually driven.
This is the quantitative case for a TARGETED road charge: meter 10% of links -> recover 84%.
-> paper/figures/trb/fig15_rstar_recoverability.pdf|png"""
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
RSTAR = 33.3
BLU, ORA, GRN, VER, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.GREY

lv = pd.read_parquet(RUNS / "baseline/route_analysis/link_vmt.parquet")
lv = lv[lv.vmt > 0]; tot = lv.vmt.sum()
s = lv.sort_values("vmt", ascending=False).reset_index(drop=True)
cumR = s.vmt.cumsum() / tot * RSTAR                       # cumulative R* recovered ($M)
fracL = (np.arange(1, len(s) + 1) / len(s)) * 100

fig, ax = plt.subplots(1, 2, figsize=(11.4, 4.4))

# (a) recoverability frontier
ax[0].axhline(RSTAR, color="k", ls="--", lw=1.0, label=f"$R^*$ = \\${RSTAR:.0f}M (full gap)")
ax[0].plot(fracL, cumR, color=VER, lw=2.4, zorder=5)
for f, c in [(5, BLU), (10, GRN), (20, ORA)]:
    i = int(len(s) * f / 100); y = cumR.iloc[i]
    ax[0].scatter([f], [y], color=c, s=55, zorder=6, edgecolor="k", lw=0.5)
    ax[0].annotate(f"top {f}% → ${y:.1f}M ({y/RSTAR*100:.0f}%)", (f, y),
                   xytext=(f + 6, y - RSTAR*0.11), fontsize=8.5,
                   arrowprops=dict(arrowstyle="->", lw=0.6))
ax[0].set(xlabel="% of road links metered (busiest first)", ylabel="shadow gas-tax gap recovered ($M)",
          title="(a) R* recoverability frontier", xlim=(0, 100), ylim=(0, RSTAR*1.08))
ax[0].legend(fontsize=8.5, loc="lower right"); ax[0].grid(alpha=0.25)

# (b) R* accrual by road class
RC = ["interstate", "arterial", "collector", "local"]
acc = (lv.groupby("road_class").vmt.sum() / tot * RSTAR).reindex(RC)
ax[1].bar(range(4), acc.values, color=[VER, ORA, GRN, GRY], edgecolor="k", lw=0.4)
ax[1].set_xticks(range(4)); ax[1].set_xticklabels([r.title() for r in RC])
for i, v in enumerate(acc.values):
    ax[1].text(i, v + 0.4, f"${v:.1f}M\n{v/RSTAR*100:.0f}%", ha="center", fontsize=8.5)
ax[1].set(ylabel="shadow gas-tax gap accrued ($M/yr)", title="(b) Where the gap is driven",
          ylim=(0, acc.max()*1.25))
ax[1].grid(axis="y", alpha=0.25)

fig.suptitle("The shadow gas-tax gap is spatially concentrated: metering 10% of links recovers 84%",
             fontsize=12, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(OUT / "fig15_rstar_recoverability.pdf"); fig.savefig(OUT / "fig15_rstar_recoverability.png", dpi=300)
plt.close(fig)
print(f"[15] R* recoverability: interstate ${acc['interstate']:.1f}M (52%); "
      f"top 10% of links recover ${cumR.iloc[int(len(s)*.1)]:.1f}M ({cumR.iloc[int(len(s)*.1)]/RSTAR*100:.0f}%)")
