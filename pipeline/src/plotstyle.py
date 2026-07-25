"""Publication-quality matplotlib style + per-figure save helper.

Each figure is saved SEPARATELY as both .pdf (vector, for LaTeX) and .png (preview).
Colorblind-safe palette (Wong 2011). Serif fonts, tight layout.
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Wong colorblind-safe palette
SURVEY = "#0072B2"   # blue  = ground truth / official
SYNTH = "#E69F00"    # orange = synthetic
ACCENT = "#009E73"   # green
GREY = "#999999"

RC = {
    "font.family": "serif",
    "font.serif": ["DejaVu Serif", "Times New Roman"],
    "mathtext.fontset": "dejavuserif",
    "font.size": 12, "axes.titlesize": 13, "axes.labelsize": 12,
    "xtick.labelsize": 10, "ytick.labelsize": 10, "legend.fontsize": 10,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
    "figure.dpi": 120, "savefig.dpi": 300, "savefig.bbox": "tight",   # 300 dpi = TRB print
    "legend.frameon": False, "axes.linewidth": 0.8,
}
plt.rcParams.update(RC)


def newfig(w=5.2, h=3.6):
    return plt.subplots(figsize=(w, h))


def save(fig, outdir, name):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(outdir / f"{name}.pdf")
    fig.savefig(outdir / f"{name}.png")
    plt.close(fig)
