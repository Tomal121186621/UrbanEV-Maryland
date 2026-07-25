#!/usr/bin/env python3
"""Two SEPARATE full-size publication maps of Maryland charging infrastructure (split for
readability): fig_map_private_charging (home density + work) and fig_map_public_charging
(L2/DCFC/Tesla + ChargePoint validation stations). Large canvas, large markers/fonts.
-> paper/figures/validation_trb/fig_map_private_charging.png / fig_map_public_charging.png"""
import sys, warnings, sqlite3
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.lines import Line2D
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = REPO/"paper/figures/validation_trb"

g = pd.read_parquet("/tmp/station_util.parquet")
home = g[g.id.str.endswith("_home")]
work = g[g.id.str.endswith("_work")]
l2   = g[g.type=="l2"]
dcfc = g[(g.type=="dcfc") & ~g.id.str.startswith("dcfc_tesla")]
tesla= g[g.id.str.startswith("dcfc_tesla")]
con = sqlite3.connect(REPO/"Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db")
cp = pd.read_sql("SELECT latitude, longitude FROM charging_station_v2 WHERE latitude IS NOT NULL", con)
cpg = gpd.GeoDataFrame(cp, geometry=gpd.points_from_xy(cp.longitude, cp.latitude), crs=4326).to_crs(26985)

tr = gpd.read_file(REPO/"pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID","geometry"]]
tr["fips"]=tr.GEOID.str[:5]; cty=tr.dissolve("fips").to_crs(26985); state=cty.dissolve()
xmin,ymin,xmax,ymax = state.total_bounds
spoly = state.geometry.iloc[0]
def clip(df):
    gg = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.x, df.y), crs=26985)
    return df[gg.within(spoly).values]
home=clip(home); work=clip(work); l2=clip(l2); dcfc=clip(dcfc); tesla=clip(tesla)

def basemap():
    fig, a = plt.subplots(figsize=(16.5, 10))
    cty.plot(ax=a, color="#f5f6f7", edgecolor="#c3c9cf", linewidth=0.8)
    a.set_xlim(xmin-4000,xmax+4000); a.set_ylim(ymin-4000,ymax+4000)
    a.set_axis_off(); a.set_aspect("equal")
    return fig, a
def finish(fig, a, name):
    state.boundary.plot(ax=a, color="#1a1a1a", linewidth=1.6, zorder=7)
    fig.tight_layout(rect=(0,0.045,1,0.97))
    fig.savefig(OUT/f"{name}.png", dpi=300, bbox_inches="tight")
    fig.savefig(OUT/f"{name}.pdf", bbox_inches="tight")
    plt.close(fig); print(f"-> {name}.png")

# ================= MAP 1: private charging =================
fig, a = basemap()
hb = a.hexbin(home.x, home.y, gridsize=100, cmap="Blues", mincnt=1, norm=LogNorm(vmin=1, vmax=3000),
              linewidths=0, extent=(xmin,xmax,ymin,ymax), zorder=2)
a.scatter(work.x, work.y, s=4, color="#C1440E", alpha=0.35, lw=0, zorder=3)
cb = fig.colorbar(hb, ax=a, fraction=0.028, pad=0.01, shrink=0.7)
cb.set_label("home chargers per cell (log scale)", fontsize=13); cb.ax.tick_params(labelsize=11)
a.set_title(f"Private charging: home-charger density (n={len(home):,}) and work chargers (n={len(work):,})",
            fontsize=18, fontweight="bold", pad=12)
fig.legend(handles=[
    Line2D([0],[0], marker="h", color="none", markerfacecolor="#6baed6", markersize=16, label="home-charger density (blue cells)"),
    Line2D([0],[0], marker="o", color="none", markerfacecolor="#C1440E", markersize=9, label=f"work chargers (n={len(work):,})")],
    loc="lower center", ncol=2, fontsize=13, frameon=False, bbox_to_anchor=(0.5, 0.01))
finish(fig, a, "fig_map_private_charging")

# ================= MAP 2: public network + validation =================
# encode ChargePoint monitoring as the STATION's own colour (no extra rings)
from scipy.spatial import cKDTree
cpxy = np.c_[cpg.geometry.x, cpg.geometry.y]
dd,_ = cKDTree(cpxy).query(l2[["x","y"]].values, k=1)
l2_cp = l2[dd<=50]; l2_rest = l2[dd>50]
fig, a = basemap()
a.scatter(l2_rest.x, l2_rest.y, s=34, color=pf.ORANGE, marker="o", edgecolor="k", lw=0.4, alpha=0.92, zorder=4)
a.scatter(l2_cp.x, l2_cp.y, s=44, color="#0B2B4E", marker="o", edgecolor="white", lw=0.5, zorder=5)
a.scatter(dcfc.x, dcfc.y, s=110, color=pf.VERM, marker="^", edgecolor="k", lw=0.6, zorder=6)
a.scatter(tesla.x, tesla.y, s=110, color=pf.PURPLE, marker="D", edgecolor="k", lw=0.6, zorder=6)
a.set_title("Public charging network and the ChargePoint validation stations",
            fontsize=18, fontweight="bold", pad=12)
fig.legend(handles=[
    Line2D([0],[0], marker="o", color="none", markerfacecolor=pf.ORANGE, markeredgecolor="k", markersize=10, label=f"public L2 (n={len(l2_rest):,})"),
    Line2D([0],[0], marker="o", color="none", markerfacecolor="#0B2B4E", markeredgecolor="white", markersize=11, label=f"L2, ChargePoint-monitored — validation (n={len(l2_cp)})"),
    Line2D([0],[0], marker="^", color="none", markerfacecolor=pf.VERM, markeredgecolor="k", markersize=13, label=f"DCFC (n={len(dcfc)})"),
    Line2D([0],[0], marker="D", color="none", markerfacecolor=pf.PURPLE, markeredgecolor="k", markersize=11, label=f"DCFC Tesla (n={len(tesla)})")],
    loc="lower center", ncol=2, fontsize=13, frameon=False, bbox_to_anchor=(0.5, 0.005))
finish(fig, a, "fig_map_public_charging")
