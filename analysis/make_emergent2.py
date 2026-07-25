#!/usr/bin/env python3
"""More GENUINELY EMERGENT simulation outputs.
  fig12_behavioral_substitution : as the public surcharge rises 0->150c, the fleet's
        emergent venue mix shifts (public energy share falls, home rises) -- price response
        that only a re-simulated, re-planning fleet can produce.
  fig13_drive_vs_charge_mismatch : where EVs DRIVE (link VMT, emergent routing) vs where
        they CHARGE (station utilization, emergent choice) -- the spatial mismatch that
        makes a per-mile road charge and a charging surcharge fall on different places.
-> paper/figures/trb/*.pdf|png"""
import sys, glob, gzip, warnings
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
OUT = REPO / "paper/figures/trb"; OUT.mkdir(parents=True, exist_ok=True)
DAYS, PLAN, RSTAR = 348.0, 3.0, 33.3
BLU, ORA, GRN, VER, PUR, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.PURPLE, pf.GREY

def latest(run):
    if not (RUNS / run / "output_plans.xml.gz").exists(): return None
    fs = sorted(glob.glob(str(RUNS / run / "ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    if not fs: return None
    d = pd.read_csv(fs[-1], sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
    return d

# ============================================ FIG 12: behavioral substitution
def fig_substitution():
    pts = [(0, "baseline_pertype")] + [(c, f"sweep_pub_{c}c") for c in [10,25,50,100,150]]
    rows = []; base_share = None
    for c, run in pts:
        d = latest(run)
        if d is None: continue
        v = d.groupby("charger_type_3way").e.sum()
        tot = v.sum()
        rows.append(dict(cents=c, home=v.get("home",0)/tot*100, work=v.get("work",0)/tot*100,
                         public=v.get("public",0)/tot*100))
    df = pd.DataFrame(rows).sort_values("cents")
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    # (a) venue shares vs price
    ax[0].plot(df.cents, df.public, "-o", color=ORA, ms=6, lw=2.2, label="public")
    ax[0].plot(df.cents, df.home, "-s", color=BLU, ms=5, lw=2, label="home")
    ax[0].plot(df.cents, df.work, "-^", color=GRN, ms=5, lw=1.8, label="work")
    ax[0].set(xlabel="public charging surcharge (¢/kWh)", ylabel="% of fleet charging energy",
              title="(a) Emergent venue substitution")
    ax[0].legend(fontsize=8.5); ax[0].grid(alpha=0.25)
    d0 = df.iloc[0]; dN = df.iloc[-1]
    ax[0].annotate(f"public {d0.public:.1f}%→{dN.public:.1f}%\nhome {d0.home:.1f}%→{dN.home:.1f}%",
                   (df.cents.iloc[-1], dN.public), xytext=(60, 30), fontsize=8,
                   arrowprops=dict(arrowstyle="->", lw=0.6))
    # (b) per-agent public-share change baseline -> +150c
    b = latest("baseline_pertype"); h = latest("sweep_pub_150c")
    def ps(d):
        g = d.groupby(["person_id","charger_type_3way"]).e.sum().unstack(fill_value=0)
        for v in ["home","work","public"]:
            if v not in g: g[v]=0.0
        return (g["public"]/g[["home","work","public"]].sum(1).clip(lower=1e-9)*100)
    j = pd.concat([ps(b).rename("b"), ps(h).rename("h")], axis=1).dropna()
    dlt = (j.h - j.b)
    ax[1].hist(dlt, bins=np.arange(-100,101,5), color=PUR, edgecolor="white", lw=0.3)
    ax[1].axvline(0, color="k", lw=0.8)
    ax[1].set(xlabel="Δ public share, baseline → +150¢ (pp)", ylabel="number of agents",
              title="(b) Per-agent response at +150¢", yscale="log")
    ax[1].text(0.04, 0.9, f"{(dlt.abs()<2).mean()*100:.0f}% shift < 2 pp\nmedian Δ {dlt.median():.1f} pp",
               transform=ax[1].transAxes, fontsize=8.5)
    ax[1].grid(alpha=0.25)
    fig.suptitle("Emergent price response: the fleet re-plans its charging as the surcharge rises",
                 fontsize=12, fontweight="bold", y=1.0)
    fig.tight_layout(rect=(0,0,1,0.96))
    fig.savefig(OUT/"fig12_behavioral_substitution.pdf"); fig.savefig(OUT/"fig12_behavioral_substitution.png", dpi=300)
    plt.close(fig)
    print(f"[12] behavioral substitution (public {d0.public:.1f}%→{dN.public:.1f}% over 0→150¢)")

# ============================================ FIG 13: drive vs charge mismatch
def fig_mismatch():
    NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
    lv = pd.read_parquet(RUNS/"baseline/route_analysis/link_vmt.parquet")
    vmap = lv.vmt.to_dict()
    # stream network: node coords, then link midpoints + VMT (low memory)
    nodes = {}; mx=[]; my=[]; mv=[]
    for _, el in ET.iterparse(gzip.open(NET,"rt"), events=("end",)):
        if el.tag=="node":
            nodes[el.get("id")]=(float(el.get("x")), float(el.get("y")))
        elif el.tag=="link":
            a=nodes.get(el.get("from")); b=nodes.get(el.get("to")); v=vmap.get(el.get("id"),0.0)
            if a and b and v>0:
                mx.append((a[0]+b[0])/2); my.append((a[1]+b[1])/2); mv.append(v)
            el.clear()
    drive = pd.DataFrame({"x":mx,"y":my,"w":mv})
    charge = pd.read_parquet("/tmp/station_util.parquet")
    charge = charge[charge.type.isin(["l2","dcfc"]) & (charge["mean"]>0)]
    tr = gpd.read_file(REPO/"pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID","geometry"]]
    tr["fips"]=tr.GEOID.str[:5]; cty=tr.dissolve("fips").to_crs(26985); state=cty.dissolve()
    xmin,ymin,xmax,ymax = state.total_bounds
    fig, ax = plt.subplots(1, 2, figsize=(12.8, 5.2))
    for a,(dat,ttl,cm) in zip(ax, [(drive,"(a) Where EVs DRIVE  (link VMT)","inferno"),
                                    (charge,"(b) Where EVs CHARGE  (station use)","viridis")]):
        cty.plot(ax=a, color="#101418", edgecolor="#333", linewidth=0.3)
        hb=a.hexbin(dat.x, dat.y, C=dat["w" if "w" in dat else "mean"], reduce_C_function=np.sum,
                    gridsize=55, cmap=cm, mincnt=1, linewidths=0, extent=(xmin,xmax,ymin,ymax))
        state.boundary.plot(ax=a, color="white", linewidth=1.0)
        a.set_axis_off(); a.set_aspect("equal"); a.set_title(ttl, fontsize=11)
        cb=fig.colorbar(hb, ax=a, fraction=0.038, pad=0.02); cb.ax.tick_params(labelsize=7)
        cb.set_label("Σ VMT" if "w" in dat else "Σ charger use", fontsize=8.5)
    fig.suptitle("Spatial mismatch: EVs drive on the interstates but charge in suburban activity centers",
                 fontsize=12.5, fontweight="bold", y=1.0)
    fig.tight_layout(rect=(0,0,1,0.97))
    fig.savefig(OUT/"fig13_drive_vs_charge_mismatch.pdf"); fig.savefig(OUT/"fig13_drive_vs_charge_mismatch.png", dpi=300)
    plt.close(fig)
    print(f"[13] drive-vs-charge mismatch ({len(drive):,} driven links, {len(charge)} charging stations)")

if __name__ == "__main__":
    fig_substitution()
    fig_mismatch()
