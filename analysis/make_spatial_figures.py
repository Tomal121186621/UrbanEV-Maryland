#!/usr/bin/env python3
"""Novel spatial/network figures for the paper — the geography of EV charging equity.
  fig09_charging_deserts : county map of (a) where captive no-home-charger EV owners
                           concentrate vs (b) DC-fast-charger access -> 'charging deserts'
                           (high captivity + low access) = where the regressive burden lands.
  fig10_policy_geography : county choropleths of mean per-agent burden under three
                           instruments (charging surcharge, MD fee, flat RUC) -> the SPATIAL
                           redistribution each policy implies.
Wong-ish sequential ramps, serif, 300 dpi. -> paper/figures/trb/*.pdf|png"""
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
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"

ev = pd.read_parquet(REPO / "pipeline/data/interim/ev_owners.parquet")
hc = pd.read_parquet(REPO / "paper/tables/per_agent_homecharger.parquet").set_index("person_id")
ev["has_home"] = ev.person_id.map(hc.has_home_charger).fillna(True)
ev["fips"] = ev.home_county.astype(str).str.zfill(5)

cty = gpd.read_file(TRACT)[["GEOID", "geometry"]]
cty["fips"] = cty.GEOID.str[:5]
cty = cty.dissolve("fips").to_crs(26985).reset_index()
state = cty.dissolve()

def choro(ax, gdf, col, cmap, title, label, vmin=None, vmax=None, pct=False):
    gdf.plot(ax=ax, column=col, cmap=cmap, edgecolor="white", linewidth=0.4,
             vmin=vmin, vmax=vmax, legend=False)
    state.boundary.plot(ax=ax, color="#222", linewidth=1.0)
    ax.set_axis_off(); ax.set_title(title, fontsize=11)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=Normalize(vmin=vmin if vmin is not None else gdf[col].min(),
                                                         vmax=vmax if vmax is not None else gdf[col].max()))
    cb = plt.colorbar(sm, ax=ax, fraction=0.038, pad=0.02)
    cb.set_label(label, fontsize=8.5); cb.ax.tick_params(labelsize=7.5)

# ---------------- FIG 9: charging deserts ----------------
g = ev.groupby("fips").agg(captive=("has_home", lambda x: (~x).mean()*100),
                           dcfc=("DCFC_5mi", "median"), n=("person_id", "size")).reset_index()
m = cty.merge(g, on="fips", how="left")
fig, ax = plt.subplots(1, 2, figsize=(11, 5.2))
choro(ax[0], m, "captive", "OrRd", "(a) Captive EV owners (no home charger)",
      "% of county EV owners without home charging", vmin=0, vmax=max(m.captive.max(), 20))
choro(ax[1], m, "dcfc", "YlGnBu", "(b) DC-fast-charger access",
      "DCFC stations within 5 mi (median owner)", vmin=0)
fig.suptitle("Two geographies of charging vulnerability: captivity (a) and fast-charger access (b)",
             fontsize=12.5, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT / "fig09_charging_deserts.pdf"); fig.savefig(OUT / "fig09_charging_deserts.png", dpi=300)
plt.close(fig); print("[09] charging deserts (captivity vs DCFC access)")

# ---------------- FIG 10: policy geography ----------------
b = pd.read_parquet(REPO / "paper/tables/per_agent_burdens.parquet")
b = b.merge(ev[["person_id", "fips"]], left_on="vehicle_id", right_on="person_id", how="left")
inst = [("T2_state_public_10c", "Charging surcharge (+10¢)", "OrRd"),
        ("md_actual", "Maryland fee ($125/$100)", "BuPu"),
        ("ruc", "Flat road-use charge", "YlGn")]
agg = b.groupby("fips").agg(**{k: (k, "mean") for k, _, _ in inst}).reset_index()
mg = cty.merge(agg, on="fips", how="left")
fig, ax = plt.subplots(1, 3, figsize=(13.2, 4.8))
for a, (k, ttl, cmap) in zip(ax, inst):
    choro(a, mg, k, cmap, ttl, "mean burden ($/owner/yr)", vmin=0)
fig.suptitle("Geography of policy incidence: mean annual EV burden by county under three instruments",
             fontsize=12.5, fontweight="bold", y=1.02)
fig.tight_layout(rect=(0, 0, 1, 0.98))
fig.savefig(OUT / "fig10_policy_geography.pdf"); fig.savefig(OUT / "fig10_policy_geography.png", dpi=300)
plt.close(fig); print("[10] policy geography (burden choropleths)")

# quick stats for the caption
worst = m.sort_values("captive", ascending=False).head(3)[["fips", "captive", "dcfc"]]
print("\nhighest-captivity counties:\n", worst.to_string(index=False))
print(f"\nstatewide captive rate: {(~ev.has_home).mean()*100:.1f}%  | "
      f"corr(captivity, DCFC access) = {m[['captive','dcfc']].corr().iloc[0,1]:.2f}")
