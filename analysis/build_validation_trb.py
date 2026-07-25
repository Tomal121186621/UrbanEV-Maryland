#!/usr/bin/env python3
"""Assemble the full per-stage validation figure suite for TRB into paper/figures/validation_trb/.
Composite panels (paper-ready), one per pipeline stage:
  val1_population   Tier 1  population CVAE   (marginals TVD, Cramer's V synth+diff, DCR)
  val2_trips        Tier 2  trip CVAE         (distance, mode, departure, daily VMT, travel time, dwell)
  val3_performance  CVAE model performance    (learning + overfit curves pop & trip, generalisation)
  val4_ev           Tier 3  EV assignment     (county totals vs MVA, BEV share, income gradient, fleet)
  val5_urbanev      Tier 4  UrbanEV charging   (ChargePoint diurnal r=0.83, weekday/weekend)
Also copies the individual source figures into per-stage subfolders for completeness."""
import os, shutil
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.image as mpimg

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
V = REPO/"pipeline/output/validation"
VE = REPO/"pipeline/output/validation_ev"
RUN = REPO/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
OUT = REPO/"paper/figures/validation_trb"; OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family":"serif","savefig.dpi":300,"figure.facecolor":"white"})

def panel(items, outname, ncol, figw=11.5, rowh=3.5):
    items = [(p,l) for p,l in items if Path(p).is_file()]
    n=len(items); nrow=(n+ncol-1)//ncol
    fig=plt.figure(figsize=(figw, rowh*nrow))
    for i,(p,lab) in enumerate(items):
        ax=fig.add_subplot(nrow,ncol,i+1); ax.imshow(mpimg.imread(p)); ax.axis("off")
        letter=lab.split(")")[0]+")"                    # just "(a)" — source panels keep their own titles
        ax.text(-0.02,1.02,letter,transform=ax.transAxes,fontsize=13,fontweight="bold",va="top",color="#0B2B4E")
    fig.subplots_adjust(left=0.02,right=0.99,top=0.98,bottom=0.01,wspace=0.04,hspace=0.06)
    fig.savefig(OUT/outname,dpi=200,bbox_inches="tight"); plt.close(fig)
    print(f"  -> {outname} ({n} panels)")

# ---- Tier 1: population CVAE (association ERROR only, per review) ----
panel([(f"{V}/A_population_marginals/fig_A_marginal_tvd.png","(a) Marginal fidelity (TVD)"),
       (f"{V}/B_joint_associations/fig_B_cramersv_diff.png","(b) Association error vs survey"),
       (f"{V}/H_memorisation/fig_H_memorisation_dcr.png","(c) Memorization / privacy (DCR)")],
      "val1_population.png", 3, rowh=3.4)

# ---- Tier 2: trips — built from data by make_trip_panel.py (uniform style); not stitched ----

# ---- CVAE model performance (2x2; generalisation panel dropped per review) ----
panel([(f"{V}/F_model_performance/fig_F_learning_population.png","(a) Population learning curve"),
       (f"{V}/F_model_performance/fig_F_overfit_population.png","(b) Population train/val (overfit)"),
       (f"{V}/F_model_performance/fig_F_learning_trip.png","(c) Trip learning curve"),
       (f"{V}/F_model_performance/fig_F_overfit_trip.png","(d) Trip train/val (overfit)")],
      "val3_model_performance.png", 2, rowh=3.4)

# ---- Tier 3: EV assignment ----
panel([(f"{VE}/A_fleet_totals/county_ev_scatter.png","(a) County EV totals vs MVA-2026"),
       (f"{VE}/A_fleet_totals/bev_share_scatter.png","(b) BEV share by county"),
       (f"{V}/E_ev_fleet/fig_E_income_gradient.png","(c) Ownership by income"),
       (f"{VE}/E_fleet_makemodel/fleet_top_models.png","(d) Fleet make/model")],
      "val4_ev_assignment.png", 2)

# ---- Tier 4: UrbanEV charging (weekend panel dropped per review) ----
panel([(f"{RUN}/validation_pertype/cp_aggregate_diurnal.png","")],
      "val5_urbanev_charging.png", 1, figw=7.5, rowh=5.2)

# ---- copy individual source figures into per-stage subfolders ----
copymap = {
    "cvae_population": list((V/"A_population_marginals").glob("*.png")) + list((V/"B_joint_associations").glob("*.png")) + list((V/"H_memorisation").glob("*.png")),
    "cvae_trips": list((V/"D_trip_marginals").glob("*.png")),
    "cvae_performance": list((V/"F_model_performance").glob("*.png")) + list((V/"G_generalisation").glob("*.png")),
    "ev_assignment": list(VE.rglob("*.png")),
    "urbanev": list((RUN/"validation_pertype").glob("*.png")),
}
for sub, files in copymap.items():
    d=OUT/sub; d.mkdir(exist_ok=True)
    for f in files:
        try: shutil.copy(f, d/f.name)
        except Exception: pass
    print(f"  [{sub}] {len(list(d.glob('*.png')))} individual figures")

print(f"\n[done] validation suite -> {OUT}")
