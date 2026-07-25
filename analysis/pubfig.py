"""pubfig.py — shared TRB/TRD publication figure style (identical to the pipeline's
src/plotstyle so every figure across the project is uniform). Colorblind-safe Wong
palette, serif fonts, 300 dpi, per-figure .pdf + .png. save() takes a figure number so
captions in FIGURE_CAPTIONS.md line up with the files."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Wong 2011 colorblind-safe palette (same roles as the pipeline)
BLUE = SURVEY = "#0072B2"     # observed / ground truth
ORANGE = SYNTH = "#E69F00"    # simulated / synthetic
GREEN = ACCENT = "#009E73"
VERM = "#D55E00"
PURPLE = "#CC79A7"
GREY = "#999999"

RC = {
    "font.family": "serif", "font.serif": ["DejaVu Serif", "Times New Roman"],
    "mathtext.fontset": "dejavuserif",
    "font.size": 12, "axes.titlesize": 13, "axes.labelsize": 12,
    "xtick.labelsize": 10, "ytick.labelsize": 10, "legend.fontsize": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "figure.dpi": 120, "savefig.dpi": 300, "savefig.bbox": "tight",
    "legend.frameon": False, "axes.linewidth": 0.8, "lines.linewidth": 2,
}
plt.rcParams.update(RC)


def newfig(w=5.2, h=3.6):
    return plt.subplots(figsize=(w, h))


def legout(ax, ncol=1, fontsize=8):
    """Place the legend OUTSIDE the axes (right) so it never overlaps the data."""
    ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), ncol=ncol,
              fontsize=fontsize, frameon=False)


def save(fig, outdir, name):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outdir / f"{name}.pdf")
    fig.savefig(outdir / f"{name}.png")
    plt.close(fig)
