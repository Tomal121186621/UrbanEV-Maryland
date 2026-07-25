#!/usr/bin/env python3
"""GENUINELY EMERGENT simulation outputs (not assumed inputs). The charger LOCATIONS are
input, but which stations agents actually use and how intensely EMERGES from the
co-evolutionary charging-choice model (range anxiety, walk cost, price, queueing) and is
validated against ChargePoint occupancy (r=0.826).
  fig11_station_utilization : MD map of every public charger sized/coloured by SIMULATED
                              occupancy + the emergent demand-concentration curve.
-> paper/figures/trb/*.pdf|png   (needs /tmp/station_util.parquet from the streaming step)"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
OUT = REPO / "paper/figures/trb"; OUT.mkdir(parents=True, exist_ok=True)

g = pd.read_parquet("/tmp/station_util.parquet")
pub = g[g.type.isin(["l2", "dcfc"])].copy()
pub["util_pct"] = pub["util"] * 100

# MD outline
tr = gpd.read_file(REPO / "pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID", "geometry"]]
tr["fips"] = tr.GEOID.str[:5]
cty = tr.dissolve("fips").to_crs(26985); state = cty.dissolve()

fig, ax = plt.subplots(1, 2, figsize=(12.6, 5.4),
                       gridspec_kw={"width_ratios": [1.55, 1]})

# ---- (a) emergent station-utilization map ----
cty.plot(ax=ax[0], color="#f4f5f6", edgecolor="white", linewidth=0.5)
state.boundary.plot(ax=ax[0], color="#222", linewidth=1.1)
used = pub[pub.peak > 0].sort_values("util_pct")
idle = pub[pub.peak == 0]
ax[0].scatter(idle.x, idle.y, s=5, color="#c9ccd1", marker="x", lw=0.5, alpha=0.6, zorder=3, label="idle (never used)")
sc = ax[0].scatter(used.x, used.y, c=used.util_pct, s=8 + used.peak * 9, cmap="plasma",
                   norm=Normalize(0, np.percentile(used.util_pct, 97)),
                   edgecolor="k", linewidth=0.2, alpha=0.9, zorder=4)
cb = fig.colorbar(sc, ax=ax[0], fraction=0.038, pad=0.02)
cb.set_label("simulated utilization (% plugs occupied)", fontsize=9)
ax[0].set_axis_off(); ax[0].set_aspect("equal")
ax[0].set_title("(a) Emergent public-charger utilization\n(marker size = peak plugs in use)", fontsize=11)
ax[0].legend(loc="lower left", fontsize=8, frameon=False)

# ---- (b) emergent demand-concentration curve ----
s = pub.sort_values("mean", ascending=False).reset_index(drop=True)
cum = s["mean"].cumsum() / s["mean"].sum() * 100
frac = (np.arange(1, len(s) + 1) / len(s)) * 100
ax[1].plot(frac, cum, color=pf.VERM, lw=2.2)
ax[1].plot([0, 100], [0, 100], "k--", lw=0.8)
i10 = int(len(s) * 0.10)
ax[1].axvline(10, color=pf.GREY, ls=":", lw=0.9)
ax[1].annotate(f"top 10% of stations\ncarry {cum.iloc[i10]:.0f}% of use",
               (10, cum.iloc[i10]), xytext=(24, 40), fontsize=9,
               arrowprops=dict(arrowstyle="->", lw=0.7))
idle_pct = (pub.peak == 0).mean() * 100
ax[1].text(0.55, 0.10, f"{idle_pct:.0f}% of stations\nnever used",
           transform=ax[1].transAxes, fontsize=9, style="italic", color=pf.GREY)
ax[1].set(xlabel="% of public stations (busiest first)", ylabel="% of charger-occupied time",
          title="(b) Emergent demand concentration", xlim=(0, 100), ylim=(0, 101))
ax[1].grid(alpha=0.25)

fig.suptitle("Where charging demand actually lands: an emergent, ChargePoint-validated ($r$=0.83) simulation output",
             fontsize=12.5, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT / "fig11_station_utilization.pdf")
fig.savefig(OUT / "fig11_station_utilization.png", dpi=300)
plt.close(fig)
print("[11] emergent station utilization + concentration")
print(f"  used {(pub.peak>0).sum()}/{len(pub)} public stations ({(pub.peak>0).mean()*100:.0f}%); "
      f"top 10% carry {cum.iloc[i10]:.0f}%; mean util {pub.util_pct.mean():.1f}%")
