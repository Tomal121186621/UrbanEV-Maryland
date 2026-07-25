#!/usr/bin/env python3
"""fig14: EMERGENT congestion response to a surcharge. Per public station, simulated
utilization under the baseline vs a +100c public surcharge. Because charging is
inelastic, the congestion map barely moves -- a per-station demonstration that the
surcharge fails to relocate infrastructure stress (only ~1pp of fleet energy shifts).
-> paper/figures/trb/fig14_congestion_shift.pdf|png"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
OUT = REPO / "paper/figures/trb"
BLU, ORA, GRN, VER, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.GREY

b = pd.read_parquet("/tmp/station_util.parquet")
p = pd.read_parquet("/tmp/station_util_100c.parquet")
b = b[b.type.isin(["l2", "dcfc"])][["id", "x", "y", "util"]].rename(columns={"util": "ub"})
p = p[p.type.isin(["l2", "dcfc"])][["id", "util"]].rename(columns={"util": "up"})
m = b.merge(p, on="id", how="inner")
m["ub"] *= 100; m["up"] *= 100; m["d"] = m.up - m.ub

tr = gpd.read_file(REPO / "pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID", "geometry"]]
tr["fips"] = tr.GEOID.str[:5]; cty = tr.dissolve("fips").to_crs(26985); state = cty.dissolve()

fig, ax = plt.subplots(1, 2, figsize=(12.4, 5.2), gridspec_kw={"width_ratios": [1, 1.5]})

# (a) baseline vs +100c per-station utilization (stickiness)
lim = max(m.ub.max(), m.up.max()) * 1.05
ax[0].plot([0, lim], [0, lim], "k--", lw=0.9, zorder=1)
ax[0].scatter(m.ub, m.up, s=14, color=BLU, alpha=0.4, edgecolor="none", zorder=3)
ax[0].set(xlabel="baseline utilization (%)", ylabel="utilization at +100¢ (%)",
          title="(a) Station utilization is sticky", xlim=(0, lim), ylim=(0, lim))
r = np.corrcoef(m.ub, m.up)[0, 1]
ax[0].text(0.05, 0.9, f"$r$ = {r:.2f}\nmean Δ {m.d.mean():+.1f} pp", transform=ax[0].transAxes, fontsize=9)
ax[0].grid(alpha=0.25)

# (b) map of the change
cty.plot(ax=ax[1], color="#f4f5f6", edgecolor="white", linewidth=0.5)
state.boundary.plot(ax=ax[1], color="#222", linewidth=1.0)
mm = m[m.d.abs() > 0.05]
vmax = np.percentile(m.d.abs(), 97) or 1
sc = ax[1].scatter(mm.x, mm.y, c=mm.d, s=10 + mm.ub * 2.5, cmap="RdBu", vmin=-vmax, vmax=vmax,
                   edgecolor="k", linewidth=0.2, alpha=0.9)
cb = fig.colorbar(sc, ax=ax[1], fraction=0.038, pad=0.02)
cb.set_label("Δ utilization at +100¢ (pp)", fontsize=9)
ax[1].set_axis_off(); ax[1].set_aspect("equal")
ax[1].set_title("(b) Where congestion shifts (mostly it doesn't)", fontsize=11)

fig.suptitle("Emergent congestion response: a +100¢ surcharge barely relocates charging demand",
             fontsize=12.5, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT / "fig14_congestion_shift.pdf"); fig.savefig(OUT / "fig14_congestion_shift.png", dpi=300)
plt.close(fig)
print(f"[14] congestion shift: per-station r={r:.2f}, mean Δ {m.d.mean():+.2f} pp, "
      f"{(m.d.abs()<1).mean()*100:.0f}% of stations move <1pp")
