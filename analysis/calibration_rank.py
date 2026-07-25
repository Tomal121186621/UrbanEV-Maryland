#!/usr/bin/env python3
"""
calibration_rank.py — composite goodness-of-fit ranking over sensitivity cells.

Reads:  output/sensitivity/calibration_scores.csv  (from sensitivity_validate.py)
Writes:
  output/sensitivity/calibration_ranking.csv
  output/sensitivity/paper_figs/G_calibration_pareto.pdf
  output/sensitivity/paper_figs/H_calibration_metric_bars.pdf

Composite loss (lower = better):

    L = w_r       * (1 - r_median)            # ChargePoint per-station correlation
      + w_rmse    * rmse_median               # ChargePoint diurnal RMSE
      + w_peak    * peak_err_median           # ChargePoint peak-hour abs err
      + w_util    * |util_gap|                # ChargePoint mean-util absolute gap
      + w_kl_e    * kl_energy                 # EVWatts session-energy KL
      + w_dcfc    * |dcfc_share_gap|          # EVWatts modal split
      + w_kl_h    * kl_start_hour             # EVWatts hour-of-start KL

Each component is min-max scaled across the cell pool BEFORE weighting, so
weights are interpretable as relative importance (sum to 1). Default weights
favour ChargePoint utilization gap (closing the over-utilization that the
SoC-unplug patch was designed to fix) and EVWatts session energy distribution.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parent.parent
SCORES = REPO_ROOT / "output" / "sensitivity" / "calibration_scores.csv"
OUT_CSV = REPO_ROOT / "output" / "sensitivity" / "calibration_ranking.csv"
FIG_DIR = REPO_ROOT / "output" / "sensitivity" / "paper_figs"

DEFAULT_WEIGHTS = {
    "r":     0.15,
    "rmse":  0.15,
    "peak":  0.10,
    "util":  0.25,   # closing the mean-util gap matters most
    "kl_e":  0.20,
    "dcfc":  0.10,
    "kl_h":  0.05,
}

FAMILY_OF = {
    "C0": "C",
    "R2": "R", "R3": "R",
    **{f"W{n}": "R" for n in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)},
    "B1": "B", "B2": "B", "B3": "B",
    "P1": "P", "P2": "P",
    "A1": "A", "A2": "A",
    "X1": "X", "X2": "X",
}
FAMILY_COLOR = {
    "C": "#000000",
    "R": "#1f78b4",
    "B": "#33a02c",
    "P": "#ff7f00",
    "A": "#6a3d9a",
    "X": "#e31a1c",
}


def minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(np.nanmin(x)), float(np.nanmax(x))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi == lo:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def composite_loss(df: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Add normalized components and composite L. Returns sorted DataFrame."""
    n = len(df)
    comp = pd.DataFrame(index=df.index)
    # Build "lower-is-better" raw arrays
    raw = {
        "r":    (1.0 - df["r_median"].values),
        "rmse": df["rmse_median"].values,
        "peak": df["peak_err_median"].values,
        "util": np.abs(df["util_gap"].values),
        "kl_e": df["kl_energy"].values,
        "dcfc": np.abs(df["dcfc_share_gap"].values),
        "kl_h": df["kl_start_hour"].values,
    }
    for k, v in raw.items():
        comp[f"raw_{k}"] = v
        comp[f"norm_{k}"] = minmax(v)
    # Weighted composite
    L = np.zeros(n)
    wsum = sum(weights.values())
    for k, w in weights.items():
        L += (w / wsum) * comp[f"norm_{k}"].values
    comp["L"] = L
    out = pd.concat([df.reset_index(drop=True),
                     comp.reset_index(drop=True)], axis=1)
    out = out.sort_values("L").reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def write_ranking(df: pd.DataFrame, path: Path) -> None:
    cols = (["rank", "cell", "L",
             "r_median", "rmse_median", "peak_err_median",
             "util_gap", "sim_mean_util", "cp_mean_util",
             "kl_energy", "dcfc_share_gap",
             "sim_dcfc_share", "evw_dcfc_share",
             "kl_start_hour", "n_matched", "n_sim_sessions"] +
            [c for c in df.columns if c.startswith("norm_")])
    df.to_csv(path, columns=cols, index=False, float_format="%.4f")
    print(f"[wrote] {path}")


def fig_g_pareto(df: pd.DataFrame, out: Path) -> None:
    """Two-axis Pareto: ChargePoint util_gap (abs) vs EVWatts KL_energy.
    Best is bottom-left corner. Colour by parameter family. Winner annotated."""
    fig, ax = plt.subplots(figsize=(6.8, 5.4))
    for _, r in df.iterrows():
        fam = FAMILY_OF.get(r["cell"], "C")
        color = FAMILY_COLOR[fam]
        ax.scatter(abs(r["util_gap"]), r["kl_energy"],
                   s=70 if r["rank"] == 1 else 36,
                   color=color, edgecolor="black", linewidth=0.7,
                   alpha=0.85, zorder=3)
        # Label every point
        offy = 7 if (r["cell"].startswith("W") and int(r["cell"][1:]) % 200 == 0) else -10
        ax.annotate(r["cell"],
                    (abs(r["util_gap"]), r["kl_energy"]),
                    textcoords="offset points", xytext=(5, offy),
                    fontsize=7.5, color=color)
    winner = df.iloc[0]
    ax.annotate(f"WINNER  L={winner['L']:.3f}",
                (abs(winner["util_gap"]), winner["kl_energy"]),
                textcoords="offset points", xytext=(14, 14),
                fontsize=9, fontweight="bold",
                arrowprops=dict(arrowstyle="->", lw=0.9))
    ax.set_xlabel("|sim − CP mean utilization|  (ChargePoint dev, n=17)")
    ax.set_ylabel("KL(sim ‖ EVWatts) on session energy (kWh, 30 bins)")
    ax.set_title("Figure G. Calibration Pareto front — "
                 "ChargePoint util gap vs EVWatts energy KL\n"
                 "(lower-left is better; bold = composite-L winner)",
                 fontsize=10.5)
    ax.grid(True, linestyle=":", alpha=0.55)
    # Family legend
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=c, label=f) for f, c in FAMILY_COLOR.items()]
    ax.legend(handles=handles, loc="upper right", title="Family",
              fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[wrote] {out}")


def fig_h_metric_bars(df: pd.DataFrame, out: Path) -> None:
    """Per-cell normalized component contributions to L (stacked horizontal
    bar). Cells sorted by L. Shows WHY each cell ranks where it does."""
    comp_keys = ["r", "rmse", "peak", "util", "kl_e", "dcfc", "kl_h"]
    comp_labels = ["1-r", "RMSE", "peak err", "|util gap|", "KL energy",
                   "|DCFC gap|", "KL start hr"]
    palette = ["#1f78b4", "#33a02c", "#a6cee3", "#e31a1c", "#ff7f00",
               "#6a3d9a", "#b2df8a"]
    weights = DEFAULT_WEIGHTS
    wsum = sum(weights.values())

    cells = df["cell"].tolist()
    y = np.arange(len(cells))
    fig, ax = plt.subplots(figsize=(8.4, max(4.0, 0.35 * len(cells) + 1.5)))
    left = np.zeros(len(cells))
    for k, lbl, col in zip(comp_keys, comp_labels, palette):
        w = weights[k] / wsum
        seg = df[f"norm_{k}"].values * w
        ax.barh(y, seg, left=left, color=col, edgecolor="white",
                linewidth=0.4, label=f"{lbl} (w={w:.2f})")
        left += seg
    # L totals annotated
    for i, (l, c) in enumerate(zip(left, cells)):
        ax.text(l + 0.005, i, f"L={l:.3f}", va="center", fontsize=7.5)
    ax.set_yticks(y)
    ax.set_yticklabels(cells)
    ax.invert_yaxis()  # rank 1 on top
    ax.set_xlabel("Weighted normalized loss components (cumulative = L)")
    ax.set_title("Figure H. Decomposition of composite calibration loss\n"
                 "(cells sorted by L; min-max-normalized components × weights)",
                 fontsize=10.5)
    ax.set_xlim(0, max(left) * 1.18)
    ax.legend(loc="lower right", fontsize=7, ncol=2, frameon=True)
    ax.grid(axis="x", linestyle=":", alpha=0.5)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"[wrote] {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", default=SCORES, type=Path)
    ap.add_argument("--out-csv", default=OUT_CSV, type=Path)
    ap.add_argument("--fig-dir", default=FIG_DIR, type=Path)
    args = ap.parse_args()

    df = pd.read_csv(args.scores)
    df = df[df["status"] == "OK"].reset_index(drop=True)
    if df.empty:
        print("ERROR: no OK rows in scores file.")
        return 2

    ranked = composite_loss(df, DEFAULT_WEIGHTS)
    args.fig_dir.mkdir(parents=True, exist_ok=True)
    write_ranking(ranked, args.out_csv)
    fig_g_pareto(ranked, args.fig_dir / "G_calibration_pareto.pdf")
    fig_h_metric_bars(ranked, args.fig_dir / "H_calibration_metric_bars.pdf")

    print("\n=== TOP 5 CELLS BY COMPOSITE L ===")
    top = ranked.head(5)[["rank", "cell", "L",
                          "r_median", "rmse_median", "util_gap",
                          "kl_energy", "dcfc_share_gap"]]
    print(top.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
