#!/usr/bin/env python3
"""
iteration_plots.py - figure-set generator consuming Java's per-iter
charging_sessions.csv (written by se.umd.stats.ChargingSessionStatsCollector).

For each iteration directory (ITERS/it.{N}/) produces:
  A. {iter}.occupancy_3way.png            home / work / public stacked area
  B. {iter}.occupancy_5way.png            home / work / L2 / DCFC / DCFC_TESLA
  C1. {iter}.sessions_by_type.png         session count by type (bar)
  C2. {iter}.energy_by_type.png           total kWh by type (bar)
  C3. {iter}.duration_kde_by_type.png     KDE of session duration per type
  C4. {iter}.soc_box_by_type.png          start/end SOC boxplot per type
  D1. {iter}.demo_type_share_income.png   type share within L/M/H income
  D2. {iter}.demo_type_share_make.png     type share within top-5 ev makes
  D3. {iter}.demo_type_share_bevphev.png  type share within BEV vs PHEV
  D4. {iter}.demo_type_share_county.png   type share within home county
                                          (requires --counties-shapefile;
                                           falls back to 25km grid cell)

Plus a cross-iter rollup under <output_dir>/analysis/:
  R1. iter_trajectory_type_share.png
  R2. iter_trajectory_energy_by_type.png
  R3. iter_trajectory_duration_by_type.png

Usage:
    python iteration_plots.py \\
        --output-dir UrbanEV-Maryland/output/calib_10pct \\
        [--counties-shapefile path/to/md_counties.shp] \\
        [--iters 0,10,20,49]        # default: all
        [--skip-per-iter]           # only emit cross-iter rollup
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Single source of truth for type ordering + colors. Mirrors the Java
# ChargerTypeOccupancyTimeProfileCollectorProvider palette.
TYPE_ORDER_5WAY = ["home", "work", "L2", "DCFC", "DCFC_TESLA"]
TYPE_COLORS_5WAY = {
    "home":       "#FF0000",
    "work":       "#0000FF",
    "L2":         "#00C800",
    "DCFC":       "#FF8C00",
    "DCFC_TESLA": "#C800C8",
}
TYPE_ORDER_3WAY = ["home", "work", "public"]
TYPE_COLORS_3WAY = {
    "home":   "#FF0000",
    "work":   "#0000FF",
    "public": "#00A000",
}
TYPE_3WAY_OF = {
    "home": "home", "work": "work",
    "L2": "public", "DCFC": "public", "DCFC_TESLA": "public", "L1": "public",
}

INCOME_ORDER = ["L", "M", "H"]
SECONDS_PER_DAY = 24 * 3600
BIN_S = 5 * 60   # 5-min bins, matches Java time-profile collectors


# --------------------------------------------------------- IO

def load_sessions_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, sep=";")
    # Drop sessions without a recognized charger_type (shouldn't happen but safe).
    df = df[df["charger_type"].notna() & df["charger_type"].astype(str).ne("")]
    # Map L1 into L2 to match the Java collector's folding decision.
    df["charger_type"] = df["charger_type"].replace({"L1": "L2"})
    df = df[df["charger_type"].isin(TYPE_ORDER_5WAY)]
    return df


def list_iter_dirs(output_dir: Path) -> list[Path]:
    iters_root = output_dir / "ITERS"
    if not iters_root.exists():
        return []
    return sorted(
        [d for d in iters_root.iterdir() if d.is_dir() and d.name.startswith("it.")],
        key=lambda p: int(p.name.split(".")[1]),
    )


def iter_num(it_dir: Path) -> int:
    return int(it_dir.name.split(".")[1])


# --------------------------------------------------------- occupancy

def bin_occupancy(df: pd.DataFrame, type_col: str, type_order: list[str]) -> pd.DataFrame:
    """Count concurrent sessions per 5-min bin per type from session intervals."""
    n_bins = SECONDS_PER_DAY // BIN_S
    out = pd.DataFrame(0, index=range(n_bins),
                       columns=type_order, dtype=int)
    if df.empty:
        return out
    # Some sessions may run past midnight (multi-day plans); clamp to [0, day]
    t0 = df["time_start_s"].clip(0, SECONDS_PER_DAY - 1).values
    t1 = df["time_end_s"].clip(0, SECONDS_PER_DAY).values
    b0 = (t0 // BIN_S).astype(int)
    b1 = np.ceil(t1 / BIN_S).astype(int).clip(0, n_bins)
    types = df[type_col].values
    for t, lo, hi in zip(types, b0, b1):
        if t in out.columns and hi > lo:
            out.loc[lo:hi - 1, t] += 1
    return out


def plot_occupancy(occ: pd.DataFrame, type_order: list[str],
                   colors: dict[str, str], title: str, out_path: Path):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x_h = occ.index * BIN_S / 3600.0
    bottom = np.zeros(len(occ))
    for t in type_order:
        ax.fill_between(x_h, bottom, bottom + occ[t].values,
                        label=t, color=colors[t], alpha=0.85, linewidth=0)
        bottom = bottom + occ[t].values
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Concurrent charging sessions")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3))
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# --------------------------------------------------------- distributions

def plot_count_bar(df: pd.DataFrame, value_col: str, title: str,
                   ylabel: str, out_path: Path):
    counts = (df.groupby("charger_type")[value_col]
              .agg("sum" if value_col != "session_id" else "count")
              .reindex(TYPE_ORDER_5WAY).fillna(0))
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(counts.index, counts.values,
                  color=[TYPE_COLORS_5WAY[t] for t in counts.index])
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, axis="y", alpha=0.3)
    for b, v in zip(bars, counts.values):
        ax.text(b.get_x() + b.get_width() / 2, v,
                f"{v:,.0f}" if v > 1000 else f"{v:.1f}",
                ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_duration_kde(df: pd.DataFrame, out_path: Path):
    fig, ax = plt.subplots(figsize=(7.5, 4))
    df = df[df["duration_s"].notna() & (df["duration_s"] > 0)]
    for t in TYPE_ORDER_5WAY:
        sub = df[df["charger_type"] == t]["duration_s"].values / 60.0  # to minutes
        if len(sub) < 5:
            continue
        # Simple Gaussian KDE
        from scipy.stats import gaussian_kde
        kde = gaussian_kde(sub)
        xs = np.linspace(0, np.percentile(sub, 99), 200)
        ax.plot(xs, kde(xs), label=f"{t} (n={len(sub)})",
                color=TYPE_COLORS_5WAY[t], linewidth=2)
    ax.set_xlabel("Session duration (min)")
    ax.set_ylabel("Density")
    ax.set_title("Session-duration KDE by charger type")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_soc_box(df: pd.DataFrame, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for ax, col, title in zip(axes,
                              ["soc_start", "soc_end"],
                              ["Start SOC by type", "End SOC by type"]):
        data, labels, colors = [], [], []
        for t in TYPE_ORDER_5WAY:
            sub = df[(df["charger_type"] == t) & df[col].notna()][col].values
            if len(sub) == 0:
                continue
            data.append(sub)
            labels.append(t)
            colors.append(TYPE_COLORS_5WAY[t])
        if not data:
            continue
        bp = ax.boxplot(data, labels=labels, patch_artist=True, showfliers=False)
        for patch, c in zip(bp["boxes"], colors):
            patch.set_facecolor(c)
            patch.set_alpha(0.7)
        ax.set_title(title)
        ax.set_ylabel("SOC (fraction)")
        ax.set_ylim(0, 1)
        ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# --------------------------------------------------------- demographics

def plot_type_share_by_group(df: pd.DataFrame, group_col: str, group_order: list[str],
                              title: str, out_path: Path):
    sub = df[df[group_col].notna() & df[group_col].astype(str).ne("")].copy()
    if sub.empty or not group_order:
        return
    counts = (sub.groupby([group_col, "charger_type"]).size()
              .unstack(fill_value=0)
              .reindex(index=group_order, columns=TYPE_ORDER_5WAY, fill_value=0))
    row_sums = counts.sum(axis=1).replace(0, np.nan)
    shares = counts.div(row_sums, axis=0).fillna(0)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bottom = np.zeros(len(shares))
    for t in TYPE_ORDER_5WAY:
        ax.bar(shares.index.astype(str), shares[t].values, bottom=bottom,
               label=t, color=TYPE_COLORS_5WAY[t], width=0.7)
        bottom = bottom + shares[t].values
    ax.set_ylim(0, 1)
    ax.set_ylabel("Share of sessions")
    ax.set_xlabel(group_col)
    ax.set_title(title)
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    # Annotate group sizes
    for i, g in enumerate(shares.index):
        n = int(row_sums.get(g, 0) or 0)
        ax.text(i, 1.01, f"n={n:,}", ha="center", va="bottom", fontsize=7)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def lookup_county(df: pd.DataFrame, counties_shp: Path | None) -> pd.Series:
    """Return a Series aligned with df.index giving a county label per row.
    Falls back to '25km grid (x,y)' if no shapefile supplied or geopandas missing."""
    if counties_shp is None:
        # Fallback: 25 km bin in EPSG:26985 (coords already in MD State Plane m)
        xb = (df["home_x"].fillna(-1) // 25_000).astype("Int64")
        yb = (df["home_y"].fillna(-1) // 25_000).astype("Int64")
        return xb.astype(str) + "," + yb.astype(str)
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        print("[warn] geopandas not installed; county lookup falls back to 25km grid",
              file=sys.stderr)
        return lookup_county(df, None)
    gdf_c = gpd.read_file(counties_shp)
    # Force to EPSG:26985 (MD State Plane NAD83 m) - sim coord system
    if gdf_c.crs is None:
        print("[warn] counties shapefile has no CRS, assuming EPSG:26985",
              file=sys.stderr)
        gdf_c.set_crs("EPSG:26985", inplace=True)
    else:
        gdf_c = gdf_c.to_crs("EPSG:26985")
    # Try common county-name columns
    name_col = next((c for c in ["NAME", "name", "COUNTY", "county", "NAMELSAD"]
                     if c in gdf_c.columns), None)
    if name_col is None:
        name_col = gdf_c.columns[0]
    pts = gpd.GeoDataFrame(
        df.assign(_idx=range(len(df))),
        geometry=[Point(x, y) if pd.notna(x) and pd.notna(y) else None
                  for x, y in zip(df["home_x"], df["home_y"])],
        crs="EPSG:26985",
    )
    joined = gpd.sjoin(pts, gdf_c[[name_col, "geometry"]],
                       how="left", predicate="within")
    return joined.sort_values("_idx")[name_col].fillna("UNKNOWN").reset_index(drop=True)


def top_n_groups(series: pd.Series, n: int) -> list[str]:
    return list(series.value_counts().head(n).index)


# --------------------------------------------------------- per-iter driver

def render_iter(it_dir: Path, counties_shp: Path | None) -> dict | None:
    it = iter_num(it_dir)
    csv_path = it_dir / f"{it}.charging_sessions.csv"
    if not csv_path.exists():
        print(f"[skip] iter {it}: no {csv_path.name}")
        return None
    df = load_sessions_csv(csv_path)
    if df.empty:
        print(f"[skip] iter {it}: 0 sessions")
        return None

    # A: 3-way occupancy
    df_3w = df.assign(charger_type_3way=df["charger_type"].map(TYPE_3WAY_OF))
    occ3 = bin_occupancy(df_3w, "charger_type_3way", TYPE_ORDER_3WAY)
    plot_occupancy(occ3, TYPE_ORDER_3WAY, TYPE_COLORS_3WAY,
                   f"Iter {it} - 24h occupancy (3-way: home / work / public)",
                   it_dir / f"{it}.occupancy_3way.png")

    # B: 5-way occupancy
    occ5 = bin_occupancy(df, "charger_type", TYPE_ORDER_5WAY)
    plot_occupancy(occ5, TYPE_ORDER_5WAY, TYPE_COLORS_5WAY,
                   f"Iter {it} - 24h occupancy (5-way)",
                   it_dir / f"{it}.occupancy_5way.png")

    # C1-C4
    plot_count_bar(df, "session_id",
                   f"Iter {it} - Sessions by charger type",
                   "Session count", it_dir / f"{it}.sessions_by_type.png")
    plot_count_bar(df, "energy_kwh",
                   f"Iter {it} - Energy delivered by charger type",
                   "Total energy (kWh)", it_dir / f"{it}.energy_by_type.png")
    plot_duration_kde(df, it_dir / f"{it}.duration_kde_by_type.png")
    plot_soc_box(df, it_dir / f"{it}.soc_box_by_type.png")

    # D1-D4
    plot_type_share_by_group(df, "income_bucket", INCOME_ORDER,
                             f"Iter {it} - Type share by income bucket",
                             it_dir / f"{it}.demo_type_share_income.png")
    top_makes = top_n_groups(df["ev_make"], 5)
    plot_type_share_by_group(df, "ev_make", top_makes,
                             f"Iter {it} - Type share by EV make (top 5)",
                             it_dir / f"{it}.demo_type_share_make.png")
    bp_order = [g for g in ["BEV", "PHEV"] if g in df["ev_type"].unique()]
    plot_type_share_by_group(df, "ev_type", bp_order,
                             f"Iter {it} - Type share by BEV vs PHEV",
                             it_dir / f"{it}.demo_type_share_bevphev.png")
    df = df.assign(home_region=lookup_county(df, counties_shp))
    top_regions = top_n_groups(df["home_region"], 12)
    plot_type_share_by_group(df, "home_region", top_regions,
                             f"Iter {it} - Type share by home region (top 12)",
                             it_dir / f"{it}.demo_type_share_county.png")

    # Stats for rollup
    by_type = df.groupby("charger_type").agg(
        n_sessions=("session_id", "count"),
        total_kwh=("energy_kwh", "sum"),
        mean_duration_min=("duration_s", lambda s: s.dropna().mean() / 60.0 if len(s) else np.nan),
    ).reindex(TYPE_ORDER_5WAY).fillna(0)
    by_type["iter"] = it
    return by_type.reset_index()


# --------------------------------------------------------- cross-iter rollup

def cross_iter_rollup(stats: pd.DataFrame, out_dir: Path):
    if stats.empty:
        return
    pivot = lambda col: (stats.pivot_table(index="iter",
                                           columns="charger_type",
                                           values=col)
                        .reindex(columns=TYPE_ORDER_5WAY))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    sessions = pivot("n_sessions").fillna(0)
    totals = sessions.sum(axis=1).replace(0, np.nan)
    shares = sessions.div(totals, axis=0).fillna(0)
    for t in TYPE_ORDER_5WAY:
        ax.plot(shares.index, shares[t].values, marker="o", markersize=3,
                label=t, color=TYPE_COLORS_5WAY[t])
    ax.set_xlabel("Iteration"); ax.set_ylabel("Share of sessions")
    ax.set_title("Type-share evolution across iterations")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "iter_trajectory_type_share.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    kwh = pivot("total_kwh").fillna(0)
    for t in TYPE_ORDER_5WAY:
        ax.plot(kwh.index, kwh[t].values, marker="o", markersize=3,
                label=t, color=TYPE_COLORS_5WAY[t])
    ax.set_xlabel("Iteration"); ax.set_ylabel("Total energy delivered (kWh)")
    ax.set_title("Energy by type across iterations")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "iter_trajectory_energy_by_type.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    dur = pivot("mean_duration_min").fillna(np.nan)
    for t in TYPE_ORDER_5WAY:
        ax.plot(dur.index, dur[t].values, marker="o", markersize=3,
                label=t, color=TYPE_COLORS_5WAY[t])
    ax.set_xlabel("Iteration"); ax.set_ylabel("Mean session duration (min)")
    ax.set_title("Mean duration by type across iterations")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "iter_trajectory_duration_by_type.png", dpi=120)
    plt.close(fig)

    stats.to_csv(out_dir / "iter_type_summary.csv", index=False)


# --------------------------------------------------------- entrypoint

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-dir", type=Path, required=True,
                    help="MATSim run output dir containing ITERS/")
    ap.add_argument("--counties-shapefile", type=Path, default=None,
                    help="Optional MD counties shapefile for D4 home-region plot")
    ap.add_argument("--iters", type=str, default=None,
                    help="Comma-sep iter numbers (default: all)")
    ap.add_argument("--skip-per-iter", action="store_true",
                    help="Only emit cross-iter rollup, skip per-iter PNGs")
    args = ap.parse_args()

    it_dirs = list_iter_dirs(args.output_dir)
    if not it_dirs:
        print(f"[fatal] no ITERS/it.* dirs under {args.output_dir}", file=sys.stderr)
        sys.exit(1)
    if args.iters:
        wanted = {int(s) for s in args.iters.split(",")}
        it_dirs = [d for d in it_dirs if iter_num(d) in wanted]
        if not it_dirs:
            print(f"[fatal] none of the requested iters exist", file=sys.stderr)
            sys.exit(1)

    summaries: list[pd.DataFrame] = []
    for d in it_dirs:
        if args.skip_per_iter:
            # Cheap path: only collect stats, no figures
            it = iter_num(d)
            csv = d / f"{it}.charging_sessions.csv"
            if not csv.exists():
                continue
            df = load_sessions_csv(csv)
            if df.empty:
                continue
            stats = df.groupby("charger_type").agg(
                n_sessions=("session_id", "count"),
                total_kwh=("energy_kwh", "sum"),
                mean_duration_min=("duration_s",
                                   lambda s: s.dropna().mean() / 60.0 if len(s) else np.nan),
            ).reindex(TYPE_ORDER_5WAY).fillna(0)
            stats["iter"] = it
            summaries.append(stats.reset_index())
        else:
            s = render_iter(d, args.counties_shapefile)
            if s is not None:
                summaries.append(s)
            print(f"[ok] iter {iter_num(d)} rendered")

    analysis_dir = args.output_dir / "analysis"
    analysis_dir.mkdir(exist_ok=True)
    if summaries:
        cross_iter_rollup(pd.concat(summaries, ignore_index=True), analysis_dir)
        print(f"[ok] cross-iter rollup written to {analysis_dir}")


if __name__ == "__main__":
    main()
