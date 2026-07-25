#!/usr/bin/env python3
"""framework_fig.py — the modeling-framework master figure (CVAE -> UrbanEV -> policy).
Swimlane bands by module type; data sources as cylinders; the two CVAEs drawn with their
encoder->latent->decoder architecture inline; validation badges on the right. Wong palette,
serif — uniform with the rest of the paper. Output paper/figures/framework.png/pdf."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Ellipse, Rectangle
from pathlib import Path

OUT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/paper/figures")
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif", "Times New Roman"],
                     "font.size": 9})

# Wong palette
BLUE, ORANGE, GREEN, TEAL, PURPLE, GREY, INK = "#0072B2", "#E69F00", "#009E73", "#2A9D8F", "#CC79A7", "#6B7280", "#1a1a1a"
F_DATA, F_GEN, F_ASN, F_SIM, F_POL, F_VAL = "#EDEFF2", "#DCEBF7", "#DBEFE3", "#D6EEF0", "#FBEBD5", "#F5E3EE"

fig, ax = plt.subplots(figsize=(13.2, 9.2))
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")


def rbox(x, y, w, h, fc, ec, lw=1.4, z=2, rad=0.015):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0.01,rounding_size={rad*100}",
                                fc=fc, ec=ec, lw=lw, zorder=z))


def txt(x, y, s, fs=9, b=True, c=INK, ha="center", va="center", it=False, z=5):
    ax.text(x, y, s, fontsize=fs, ha=ha, va=va, zorder=z, color=c,
            fontweight="bold" if b else "normal", style="italic" if it else "normal")


def cylinder(cx, cy, w, h, label, fc=F_DATA, ec=GREY):
    e = h * 0.16
    ax.add_patch(Rectangle((cx - w/2, cy - h/2 + e), w, h - 2*e, fc=fc, ec="none", zorder=3))
    ax.add_patch(Ellipse((cx, cy - h/2 + e), w, 2*e, fc=fc, ec=ec, lw=1.1, zorder=3))
    ax.add_patch(Ellipse((cx, cy + h/2 - e), w, 2*e, fc=fc, ec=ec, lw=1.1, zorder=4))
    ax.plot([cx - w/2, cx - w/2], [cy - h/2 + e, cy + h/2 - e], color=ec, lw=1.1, zorder=3)
    ax.plot([cx + w/2, cx + w/2], [cy - h/2 + e, cy + h/2 - e], color=ec, lw=1.1, zorder=3)
    txt(cx, cy, label, fs=7.6, b=True, c="#333")


def arrow(x0, y0, x1, y1, c=INK, lw=1.8, rad=0.0, z=1, style="-|>"):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style, mutation_scale=13,
                                 lw=lw, color=c, zorder=z, connectionstyle=f"arc3,rad={rad}"))


def band(y, h, fc, ec, tab):
    ax.add_patch(FancyBboxPatch((3, y), 94, h, boxstyle="round,pad=0.01,rounding_size=1.2",
                                fc=fc, ec=ec, lw=1.3, alpha=0.55, zorder=1))
    ax.add_patch(FancyBboxPatch((3, y), 2.0, h, boxstyle="round,pad=0.01,rounding_size=1.2",
                                fc=ec, ec=ec, zorder=1))
    ax.text(1.7, y + h/2, tab, rotation=90, ha="center", va="center", fontsize=9.5,
            fontweight="bold", color=ec, zorder=2)


def cvae(x, y, w, h, title, cond=False):
    """Draw a mini encoder->z->decoder architecture inside a model box."""
    rbox(x, y, w, h, "white", BLUE, lw=1.6, z=3)
    txt(x + w/2, y + h - 2.0, title, fs=8.6, c=BLUE)
    ex = x + 1.6; ew = (w - 5) / 3.0; ey = y + 1.3; eh = h - 5.2
    for i, (lab, fc) in enumerate([("enc", F_GEN), ("z", "white"), ("dec", F_GEN)]):
        bx = ex + i * (ew + 0.7)
        ax.add_patch(FancyBboxPatch((bx, ey), ew, eh, boxstyle="round,pad=0.01,rounding_size=0.5",
                                    fc=fc, ec=BLUE, lw=1.0, zorder=4))
        txt(bx + ew/2, ey + eh/2, lab, fs=7.2, c=INK)
        if i < 2:
            arrow(bx + ew, ey + eh/2, bx + ew + 0.7, ey + eh/2, c=BLUE, lw=1.1, z=5)
    if cond:
        txt(x + w/2, y + 0.6, "cond: person + HH", fs=6.4, b=False, c=PURPLE, it=True)


def badge(x, y, s):
    ax.add_patch(FancyBboxPatch((x, y), 15.5, 3.4, boxstyle="round,pad=0.01,rounding_size=1.0",
                                fc=F_VAL, ec=PURPLE, lw=1.2, zorder=4))
    txt(x + 7.75, y + 1.7, s, fs=6.9, b=True, c="#7A2E5D")


def darrow(x0, y0, x1, y1, c=GREY, lw=1.1):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=10,
                                 lw=lw, color=c, ls=(0, (3, 2)), zorder=1))

def carrow(x0, y0, x1, y1, c=INK, lw=2.0, rad=-0.25):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=14,
                                 lw=lw, color=c, zorder=2, connectionstyle=f"arc3,rad={rad}"))

# ---------------- bands ----------------
band(64, 22.0, F_GEN, BLUE, "GENERATIVE")
band(41, 20.0, F_ASN, GREEN, "ASSIGNMENT")
band(23.5, 13.5, F_SIM, TEAL, "SIMULATION")
band(3.5, 17.5, F_POL, ORANGE, "POLICY")

# ---------------- inputs (cylinders — own row above everything) ----------------
txt(50, 99.0, "Observed data inputs", fs=10, c=GREY)
inputs = [("RTS / MTS\nTravel Survey", 14), ("MVA-2026\nRegistrations", 32),
          ("AFDC\nCharging Sites", 50), ("OSM POIs +\nMD Network", 68), ("NREL-278\nCharger Access", 86)]
for lab, cx in inputs:
    cylinder(cx, 94.0, 12, 6.0, lab)
    darrow(cx, 91.0, cx, 86.5)                      # feed down into the framework

# ---------------- generative band ----------------
cvae(8, 66, 26, 18.0, "Household CVAE")
cvae(37, 66, 26, 18.0, "Trip CVAE (conditional)", cond=True)
rbox(67, 68, 27, 14.0, "white", BLUE, lw=1.5)
txt(80.5, 79.5, "Synthetic Maryland", fs=9, c=BLUE)
txt(80.5, 76.0, "population + activity", fs=8.2, b=False)
txt(80.5, 73.3, "trip chains", fs=8.2, b=False)
txt(80.5, 70.2, "(feasibility-repaired)", fs=7.0, b=False, c=GREY, it=True)

# ---------------- assignment band ----------------
for x, lab in [(8, "EV Ownership\nLogit\n(MVA-calibrated)"), (30.5, "Vehicle & Charger\nAssignment\n(make/model, NREL)"),
               (53, "Activity-Location\nGeolocation\n(OSM-POI)"), (75.5, "MATSim Plans\n+ electric\nvehicles")]:
    rbox(x, 43.0, 20, 15.5, "white", GREEN, lw=1.5)
    txt(x + 10, 50.75, lab, fs=8.0)

# ---------------- simulation band ----------------
rbox(9, 25.5, 46, 9.5, "white", TEAL, lw=1.6)
txt(32, 32.2, "UrbanEV MATSim charging simulation", fs=9.2, c=TEAL)
txt(32, 28.4, "co-evolutionary replanning: range anxiety · walk · per-kWh cost", fs=7.2, b=False)
ax.add_patch(FancyArrowPatch((49, 30.2), (49, 33.0), arrowstyle="-|>", mutation_scale=10, lw=1.2,
                             color=TEAL, connectionstyle="arc3,rad=1.2", zorder=3))
txt(54.5, 31.6, "replan", fs=6.3, b=False, c=TEAL, it=True)
rbox(63, 26.0, 30, 8.5, "white", TEAL, lw=1.4)
txt(78, 32.0, "Charging sessions", fs=8.4, c=TEAL)
txt(78, 28.4, "+ base mobility (VMT)", fs=7.6, b=False)

# ---------------- policy band ----------------
for x, lab, sub in [(8, "Shadow Gas-Tax\nGap  $R^{*}$", "iter-0 VMT × mpg⁻¹ × τ"),
                    (37, "Recovery\nInstruments", "charging · registration · RUC"),
                    (66, "Incidence &\nEquity", "Suits index · winners/losers")]:
    rbox(x, 5.5, 26, 11.0, "white", ORANGE, lw=1.5)
    txt(x + 13, 12.8, lab, fs=8.6, c="#9A6A10")
    txt(x + 13, 8.0, sub, fs=6.8, b=False, c=GREY, it=True)

# ---------------- flow arrows ----------------
arrow(34, 75, 37, 75, c=BLUE)                       # HH CVAE -> Trip CVAE
arrow(63, 75, 67, 75, c=BLUE)                       # Trip CVAE -> synth
carrow(70, 68, 18, 58.5, c=INK, rad=0.28)           # synth -> EV ownership (first assignment step)
for x0, x1 in [(28, 30.5), (50.5, 53), (73, 75.5)]:  # assignment left-to-right
    arrow(x0, 50.75, x1, 50.75, c=GREEN)
carrow(85.5, 43.0, 32, 35.0, c=INK, rad=0.28)        # plans -> UrbanEV simulation
arrow(55, 30.0, 63, 30.0, c=INK, lw=1.6)             # UrbanEV -> sessions
carrow(20, 25.5, 21, 16.5, c=INK, rad=0.0)           # simulation -> shadow gap
arrow(34, 11.0, 37, 11.0, c=ORANGE)                  # R* -> instruments
arrow(63, 11.0, 66, 11.0, c=ORANGE)                  # instruments -> incidence

# ---------------- validation badges ----------------
badge(62.5, 62.0, "V1–V2: held-out\nTVD, Cramér's V, DCR")
badge(62.5, 38.5, "V3: county EV\nvs MVA (r=1.00)")
badge(36, 20.2, "V4: charging vs\nChargePoint (r=0.82)")

# legend
lx = 6
for i, (c, lab) in enumerate([(BLUE, "generative (plain CVAE)"), (GREEN, "assignment"),
                              (TEAL, "MATSim simulation"), (ORANGE, "policy analysis"),
                              (PURPLE, "validation checkpoint"), (GREY, "observed data")]):
    ax.add_patch(Rectangle((lx + i*15.5, 0.4), 1.6, 1.6, fc=c, ec=c, zorder=5))
    ax.text(lx + i*15.5 + 2.1, 1.2, lab, fontsize=7.0, va="center", color="#333")
fig.savefig(OUT / "framework.png", dpi=260, bbox_inches="tight")
fig.savefig(OUT / "framework.pdf", bbox_inches="tight")
print("-> framework.png / .pdf")
