#!/usr/bin/env python3
"""
validation_tier_figs.py — assemble four tiered validation figures for the TRB paper, one per
upstream model layer, each a multi-panel composite of the existing diagnostic plots:
  Tier 1  population synthesis  (marginals, associations, memorization)
  Tier 2  trip/activity generation (distance, mode, departure, daily VMT)
  Tier 3  EV ownership/assignment (county totals, income gradient, BEV share, fleet)
  Tier 4  charging behavior (diurnal profile, venue by home access)
Output -> paper/figures/  (single figures so each counts once toward the TRB exhibit budget).
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

REPO = "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB"
V = os.path.join(REPO, "pipeline/output/validation")
VE = os.path.join(REPO, "pipeline/output/validation_ev")
RUN = os.path.join(REPO, "UrbanEV-Maryland/scenarios/maryland/output/runs_2026")
OUT = os.path.join(REPO, "paper/figures")
plt.rcParams.update({"font.family": "serif", "savefig.dpi": 300, "figure.facecolor": "white"})


def panel(paths, labels, ncol, outname, figw, rowh):
    paths = [(p, l) for p, l in zip(paths, labels) if os.path.isfile(p)]
    n = len(paths); nrow = (n + ncol - 1) // ncol
    fig = plt.figure(figsize=(figw, rowh * nrow))
    for i, (p, lab) in enumerate(paths):
        ax = fig.add_subplot(nrow, ncol, i + 1)
        ax.imshow(mpimg.imread(p)); ax.axis("off")
        letter = lab.split(")")[0] + ")"                       # "(a)" only — source panels keep their own titles
        ax.text(-0.01, 1.0, letter, transform=ax.transAxes, fontsize=13, fontweight="bold",
                va="top", ha="left", color="#0B2B4E")
    fig.subplots_adjust(left=0.02, right=0.99, top=0.99, bottom=0.01, wspace=0.04, hspace=0.06)
    fig.savefig(os.path.join(OUT, outname), dpi=200, bbox_inches="tight")
    plt.close(fig); print("->", outname, f"({n} panels)")


# Tier 1 — population synthesis
panel([f"{V}/A_population_marginals/fig_A_marginal_tvd.png",
       f"{V}/B_joint_associations/fig_B_cramersv_synth.png",
       f"{V}/B_joint_associations/joints/joint_hh_income_detailed__home_type.png",
       f"{V}/H_memorisation/fig_H_memorisation_dcr.png"],
      ["(a) Marginal fidelity (TVD by attribute)", "(b) Joint associations (Cramér's V)",
       "(c) Example joint: income × dwelling", "(d) Memorization check (DCR)"],
      2, "val_tier1_population.png", 11.5, 3.6)

# Tier 2 — trip / activity generation
panel([f"{V}/D_trip_marginals/trip_distance.png", f"{V}/D_trip_marginals/trip_mode.png",
       f"{V}/D_trip_marginals/trip_departure_hour_all.png", f"{V}/D_trip_marginals/fig_D_daily_vmt.png"],
      ["(a) Trip distance", "(b) Travel mode", "(c) Departure hour", "(d) Daily VMT vs. survey"],
      2, "val_tier2_trips.png", 11.5, 3.4)

# Tier 3 — EV ownership / assignment
panel([f"{VE}/A_fleet_totals/county_ev_scatter.png", f"{VE}/B_adoption_gradient/ownership_by_income.png",
       f"{VE}/A_fleet_totals/bev_share_scatter.png", f"{VE}/E_fleet_makemodel/fleet_top_models.png"],
      ["(a) County EV totals vs. MVA-2026", "(b) Adoption gradient by income",
       "(c) BEV share by county", "(d) Fleet make/model"],
      2, "val_tier3_ev.png", 11.5, 3.6)

# Tier 4 — charging behavior (expanded: diurnal + weekday/weekend vs ChargePoint,
# venue by home access, start-SOC by venue)
panel([f"{RUN}/validation/cp_aggregate_diurnal.png",
       f"{RUN}/validation/cp_weekday_weekend.png",
       f"{RUN}/baseline/charging_profiles/venue_by_homeaccess.png",
       f"{RUN}/baseline/charging_profiles/start_soc_by_venue.png"],
      ["(a) Public diurnal profile vs. ChargePoint", "(b) Weekday vs. weekend vs. ChargePoint",
       "(c) Charging venue by home-charger access", "(d) Start-of-charge SOC by venue"],
      2, "val_tier4_charging.png", 11.5, 3.6)

print("[done] 4 tier validation figures ->", OUT)
