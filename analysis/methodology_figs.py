#!/usr/bin/env python3
"""
methodology_figs.py — three methodology figures for the TRB paper, uniform pubfig style,
built ONLY from real pipeline outputs (no fabricated numbers):

  FIG 1  study_area.png             Maryland county choropleth (EV owners) + charger points
  FIG 2  ownership_coefficients.png Burra-Cirillo (2024) EV-ownership logit coefficients
  FIG 3  home_charger_access.png    Home-charger access by dwelling type x tenure, as
                                     actually assigned in the MATSim plans population

Run:  .venv/bin/python UrbanEV-Maryland/analysis/methodology_figs.py   (from repo root)
"""
import gzip
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf

REPO = Path(__file__).resolve().parents[2]        # repo root (has pipeline/, Input/, paper/)
sys.path.insert(0, str(REPO / "pipeline"))
from src.labels import HOME_TYPE, HOME_OWNERSHIP, COUNTY  # noqa: E402

EVO = REPO / "pipeline/data/interim/ev_owners.parquet"
TRACT = REPO / "pipeline/data/geo/tl_2020_24_tract.shp"
POP = REPO / "pipeline/data/geo/md_county_pop.csv"
CHG = REPO / "Input/chargers/chargers.xml"
PLANS = REPO / "Input/population/plans_maryland_ev_2026.xml.gz"
OUTDIR = REPO / "paper/figures"


# --------------------------------------------------------------------------------------
# FIG 1 — study area: county EV-owner choropleth + charger points
# --------------------------------------------------------------------------------------
def fig1_study_area():
    from matplotlib.colors import LogNorm
    from matplotlib.ticker import FixedLocator, FuncFormatter

    ev = pd.read_parquet(EVO, columns=["home_county"])
    ev_cnt = ev["home_county"].value_counts().rename("n_ev").rename_axis("fips").reset_index()

    cty = gpd.read_file(TRACT)
    cty["fips"] = cty["GEOID"].str[:5]
    cty = cty.dissolve("fips", as_index=False).to_crs("EPSG:26985")
    cty = cty.merge(ev_cnt, on="fips", how="left")
    cty["n_ev"] = cty["n_ev"].fillna(0)
    cty["county_name"] = cty["fips"].map(COUNTY)
    assert cty["fips"].nunique() == 24, f"expected 24 counties, got {cty['fips'].nunique()}"
    state = cty.dissolve()                       # single Maryland outline

    # charger locations (L1 dropped per design — only 2 statewide)
    txt = CHG.read_text()
    rows = re.findall(r'<charger [^>]*type="([^"]+)"[^>]*x="([-0-9.]+)"[^>]*y="([-0-9.]+)"', txt)
    ch = pd.DataFrame(rows, columns=["type", "x", "y"])
    ch[["x", "y"]] = ch[["x", "y"]].apply(pd.to_numeric)
    ch["grp"] = np.where(ch["type"].str.contains("DCFC"), "DCFC",
                          np.where(ch["type"] == "L2", "L2", "L1"))
    l2 = ch[ch.grp == "L2"]; dc = ch[ch.grp == "DCFC"]

    # log-scaled sequential fill so Montgomery (46,667) doesn't wash out small counties
    vmin, vmax = float(cty["n_ev"].min()), float(cty["n_ev"].max())
    norm = LogNorm(vmin=max(vmin, 50), vmax=vmax)

    fig, ax = pf.newfig(8.4, 9.4)
    cty.plot(ax=ax, column="n_ev", cmap="YlGnBu", norm=norm,
              edgecolor="white", linewidth=0.7, legend=False, zorder=1)
    state.boundary.plot(ax=ax, edgecolor="0.15", linewidth=1.6, zorder=2)

    h_l2 = ax.scatter(l2.x, l2.y, s=9, c=pf.VERM, alpha=0.7, linewidths=0, zorder=3,
                      label=f"L2 charger (n={len(l2):,})")
    h_dc = ax.scatter(dc.x, dc.y, s=26, marker="^", facecolor="none",
                      edgecolor="k", linewidths=0.7, zorder=4,
                      label=f"DCFC charger (n={len(dc):,})")

    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.grid(False)
    ax.margins(0.02)
    ax.set_title("Maryland study area: EV owners by county and public charging",
                 pad=10)

    # colorbar on its own, right side (steals space from ax -> no overlap)
    sm = plt.cm.ScalarMappable(cmap="YlGnBu", norm=norm); sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.02, aspect=28)
    ticks = [100, 300, 1000, 3000, 10000, 30000]
    ticks = [t for t in ticks if vmin <= t <= vmax]
    cb.set_ticks(FixedLocator(ticks).tick_values(vmin, vmax))
    cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    cb.set_label("EV owners per county (log scale)")

    # charger legend OUTSIDE the map, below it, framed — never overlaps the state
    ax.legend(handles=[h_l2, h_dc], loc="upper center", bbox_to_anchor=(0.5, -0.02),
              ncol=2, fontsize=9, markerscale=1.6, frameon=True, framealpha=0.95,
              edgecolor="0.7", handletextpad=0.4, columnspacing=1.8)

    # scale bar, lower-left (empty SW corner of the map)
    x0 = ax.get_xlim()[0] + 12000
    y0 = ax.get_ylim()[0] + 16000
    ax.plot([x0, x0 + 20000], [y0, y0], color="k", lw=2, zorder=6)
    ax.text(x0 + 10000, y0 + 4500, "20 km", ha="center", fontsize=8)

    pf.save(fig, OUTDIR, "study_area")
    print(f"[fig1] {len(cty)} counties (all drawn), EV/county range "
          f"{int(vmin):,}-{int(vmax):,}; chargers plotted L2={len(l2):,}, DCFC={len(dc):,} "
          f"(L1 dropped, n={int((ch.grp=='L1').sum())})")
    return cty, ch


# --------------------------------------------------------------------------------------
# FIG 2 — EV-ownership logit coefficients (Burra-Cirillo 2024), as used in 04_ev_ownership_cirillo.py
# --------------------------------------------------------------------------------------
def fig2_ownership_coefficients():
    BETA = dict(income=0.305, single_family=0.479, numbicycle=0.136, numworkers=-0.269,
                transit_trips=-0.044, auto_distance=-0.004, home_office=0.783,
                charge_at_work=0.799, L2_1km=0.011, DCFC_5mi=0.032)
    LABELS = {
        "income": "Household income",
        "single_family": "Single-family home",
        "numbicycle": "No. bicycles",
        "numworkers": "No. workers",
        "transit_trips": "Transit trips",
        "auto_distance": "Auto-dependence dist.",
        "home_office": "Home office",
        "charge_at_work": "Workplace charging",
        "L2_1km": "L2 within 1 km",
        "DCFC_5mi": "DCFC within 5 mi",
    }

    df = pd.DataFrame({"var": list(BETA.keys()), "beta": list(BETA.values())})
    df["label"] = df["var"].map(LABELS)
    df = df.sort_values("beta").reset_index(drop=True)
    colors = [pf.GREEN if b > 0 else pf.VERM for b in df["beta"]]

    fig, ax = pf.newfig(6.4, 4.6)
    y = np.arange(len(df))
    ax.barh(y, df["beta"], color=colors, height=0.6, zorder=3)
    ax.axvline(0, color="0.3", lw=0.8, zorder=2)
    ax.set_yticks(y)
    ax.set_yticklabels(df["label"])
    ax.set_xlabel("Coefficient (binomial-logit utility)")
    ax.set_title("EV-ownership model coefficients (Burra–Cirillo 2024)")

    for yi, b in zip(y, df["beta"]):
        ax.text(b + (0.02 if b > 0 else -0.02), yi, f"{b:+.3f}",
                 va="center", ha="left" if b > 0 else "right", fontsize=8)

    ax.margins(x=0.18)
    pf.save(fig, OUTDIR, "ownership_coefficients")
    print(f"[fig2] {len(df)} coefficients plotted (const=-7.676, not shown); "
          f"range {df['beta'].min():+.3f} to {df['beta'].max():+.3f}")
    return df


# --------------------------------------------------------------------------------------
# FIG 3 — home-charger access by dwelling type x tenure, from the ACTUAL assigned
# MATSim plans population (Input/population/plans_maryland_ev_2026.xml.gz), which
# encodes the outcome of scripts/assign_home_chargers.py's NREL-278 / Ge-2021 /
# PIA-2023 assignment rule (see UrbanEV-Maryland/scripts/assign_home_chargers.py).
# --------------------------------------------------------------------------------------
def parse_plans_home_charger():
    RE_ATTR = re.compile(r'<attribute name="(\w+)"[^>]*>([^<]*)</attribute>')
    want = {"home_type", "home_ownership", "homeChargerPower"}
    recs = []
    cur = {}
    with gzip.open(PLANS, "rt", encoding="utf-8") as f:
        for line in f:
            if "<person id=" in line:
                cur = {}
                continue
            m = RE_ATTR.search(line)
            if m and m.group(1) in want:
                cur[m.group(1)] = m.group(2).strip()
                if m.group(1) == "homeChargerPower":
                    if "home_type" in cur and "home_ownership" in cur:
                        recs.append((cur["home_type"], cur["home_ownership"],
                                      float(cur["homeChargerPower"])))
                    cur = {}
    return pd.DataFrame(recs, columns=["home_type", "home_ownership", "kw"])


def fig3_home_charger_access():
    if not PLANS.exists():
        print(f"[fig3] SKIPPED — plans file not found: {PLANS}")
        return None

    df = parse_plans_home_charger()
    if df.empty:
        print("[fig3] SKIPPED — no homeChargerPower / home_type / home_ownership "
              "attributes found in plans population; cannot plot real assignment data.")
        return None

    df["has_charger"] = df["kw"] > 0
    df["dwelling"] = df["home_type"].map(HOME_TYPE)
    df["tenure"] = df["home_ownership"].map(HOME_OWNERSHIP)

    g = (df.groupby(["dwelling", "tenure"])["has_charger"]
           .agg(["mean", "count"]).reset_index())

    dwell_order = [HOME_TYPE[k] for k in sorted(HOME_TYPE, key=int) if HOME_TYPE[k] in g["dwelling"].unique()]
    tenure_order = [HOME_OWNERSHIP[k] for k in sorted(HOME_OWNERSHIP, key=int) if HOME_OWNERSHIP[k] in g["tenure"].unique()]

    fig, ax = pf.newfig(6.8, 4.8)
    n_dw = len(dwell_order); n_ten = len(tenure_order)
    width = 0.8 / n_ten
    x = np.arange(n_dw)
    palette = [pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.PURPLE]

    for i, ten in enumerate(tenure_order):
        vals, counts = [], []
        for dw in dwell_order:
            row = g[(g.dwelling == dw) & (g.tenure == ten)]
            if len(row):
                vals.append(row["mean"].iloc[0] * 100)
                counts.append(int(row["count"].iloc[0]))
            else:
                vals.append(np.nan)
                counts.append(0)
        xpos = x + (i - (n_ten - 1) / 2) * width
        bars = ax.bar(xpos, vals, width=width * 0.92, color=palette[i % len(palette)],
                       label=f"{ten} (n={sum(counts):,})", zorder=3)
        for b, c in zip(bars, counts):
            if c > 0:
                ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1, f"{c:,}",
                         ha="center", va="bottom", fontsize=6, rotation=90)

    ax.set_xticks(x)
    ax.set_xticklabels(dwell_order)
    ax.set_ylabel("Share with home-charger access (%)")
    ax.set_xlabel("Dwelling type")
    ax.set_title("Home-charging access by dwelling type × tenure (assigned)", pad=10)
    ax.set_ylim(0, 118)
    ax.legend(fontsize=8, ncol=n_ten, loc="lower center", bbox_to_anchor=(0.5, -0.32), frameon=False)
    fig.text(0.5, -0.02,
              "Source: assigned home-charger access, NREL submission 278 / Ge et al. (2021) / "
              "Plug In America (2023) — see scripts/assign_home_chargers.py",
              ha="center", fontsize=7, color="0.35")

    pf.save(fig, OUTDIR, "home_charger_access")
    overall = df["has_charger"].mean()
    print(f"[fig3] n={len(df):,} EV-owner agents in plans population; "
          f"overall access={overall*100:.1f}%; cells={len(g)}")
    return g


if __name__ == "__main__":
    OUTDIR.mkdir(parents=True, exist_ok=True)
    fig1_study_area()
    fig2_ownership_coefficients()
    fig3_home_charger_access()
