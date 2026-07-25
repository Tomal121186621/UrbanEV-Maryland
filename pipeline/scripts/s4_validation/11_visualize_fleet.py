#!/usr/bin/env python3
"""
11_visualize_fleet.py — TRB-style visualization of the assigned Maryland EV make/model
fleet (multinomial draw from MD registration shares, split by BEV/PHEV).
Reads the assigned electric_vehicles.xml + the fleet lookup; writes figures to
output/validation_ev/E_fleet_makemodel/.
"""
from __future__ import annotations
import sys, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.plotstyle import newfig, save, SURVEY, SYNTH, ACCENT, GREY
import matplotlib.pyplot as plt

VEH = ROOT / "pipeline/output/plans/electric_vehicles.xml"
LOOK = ROOT / "pipeline/data/reference/vehicles/ev_counterfactual_mpg_lookup.csv"
OUT = ROOT / "pipeline/output/validation_ev/E_fleet_makemodel"

MAKE = {
    "model_y": "Tesla", "model_3": "Tesla", "model_s": "Tesla", "model_x": "Tesla",
    "cybertruck": "Tesla", "ix_i4_i5_i7": "BMW", "x5_x3_330e_530e": "BMW",
    "rav4_prime": "Toyota", "prius_prime": "Toyota", "bz4x": "Toyota", "nx_rx_phev": "Lexus",
    "mustang_mach_e": "Ford", "f_150_lightning": "Ford", "escape_phev": "Ford",
    "aviator_corsair_phev": "Lincoln", "lyriq": "Cadillac", "equinox_ev": "Chevrolet",
    "blazer_ev": "Chevrolet", "r1s": "Rivian", "r1t": "Rivian", "eqs_eqe_eqb": "Mercedes-Benz",
    "gle_glc_s_class_phev": "Mercedes-Benz", "e_tron_q4_q6_q8": "Audi", "taycan_macan": "Porsche",
    "cayenne_panamera_phev": "Porsche", "wrangler_4xe": "Jeep", "grand_cherokee_4xe": "Jeep",
    "pacifica_hybrid": "Chrysler", "ioniq_5": "Hyundai", "tucson_phev": "Hyundai",
    "ev6": "Kia", "ev9": "Kia", "id_4": "Volkswagen", "prologue": "Honda", "2_3_4": "Polestar",
    "ex30_ex90_xc40": "Volvo", "xc60_s60_s90_phev": "Volvo", "air_gravity": "Lucid",
    "gv60_electrified": "Genesis", "outlander_phev": "Mitsubishi",
}
NICE = {"model_y": "Model Y", "model_3": "Model 3", "model_s": "Model S", "model_x": "Model X",
        "cybertruck": "Cybertruck", "ix_i4_i5_i7": "iX/i4/i5/i7", "x5_x3_330e_530e": "X5/X3/330e",
        "rav4_prime": "RAV4 Prime", "prius_prime": "Prius Prime", "mustang_mach_e": "Mach-E",
        "f_150_lightning": "F-150 Lightning", "lyriq": "Lyriq", "equinox_ev": "Equinox EV",
        "blazer_ev": "Blazer EV", "r1s": "R1S", "r1t": "R1T", "eqs_eqe_eqb": "EQS/EQE/EQB",
        "e_tron_q4_q6_q8": "e-tron Q4/Q6/Q8", "ioniq_5": "Ioniq 5", "id_4": "ID.4", "ev6": "EV6",
        "ev9": "EV9", "model_x": "Model X", "prologue": "Prologue", "2_3_4": "Polestar 2/3/4",
        "wrangler_4xe": "Wrangler 4xe", "grand_cherokee_4xe": "Grand Cherokee 4xe"}


def nice(t):
    return NICE.get(t, t.replace("_", " ").title())


def main():
    txt = VEH.read_text()
    types = re.findall(r'vehicle_type="([^"]+)"', txt)
    df = pd.DataFrame({"ev_type": types})
    look = pd.read_csv(LOOK)
    pt = dict(zip(look.ev_type, look.powertrain.str.upper()))
    share = dict(zip(look.ev_type, look.fleet_share_pct))
    df["make"] = df.ev_type.map(MAKE).fillna("Other")
    df["powertrain"] = df.ev_type.map(pt).fillna("BEV")
    N = len(df)
    print(f"[fleet] {N:,} vehicles | BEV {(df.powertrain=='BEV').mean():.3f}")

    # ---- Fig 1: top models, BEV vs PHEV -----------------------------------
    top = df.ev_type.value_counts().head(22)[::-1]
    cols = [SURVEY if pt.get(t, "BEV") == "BEV" else SYNTH for t in top.index]
    fig, ax = newfig(6.4, 7)
    ax.barh([nice(t) for t in top.index], top.values / N * 100, color=cols, edgecolor="k", lw=0.3)
    ax.set(xlabel="share of Maryland EV fleet (%)", title="Assigned EV models (Maryland 2026)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=SURVEY, label="BEV"), Patch(color=SYNTH, label="PHEV")], loc="lower right")
    save(fig, OUT, "fleet_top_models")

    # ---- Fig 2: by make, stacked BEV/PHEV ---------------------------------
    mk = df.groupby(["make", "powertrain"]).size().unstack(fill_value=0)
    mk["tot"] = mk.sum(1); mk = mk.sort_values("tot", ascending=True)
    fig, ax = newfig(6, 7)
    bev = mk.get("BEV", 0) / N * 100; phev = mk.get("PHEV", 0) / N * 100
    ax.barh(mk.index, bev, color=SURVEY, edgecolor="k", lw=0.3, label="BEV")
    ax.barh(mk.index, phev, left=bev, color=SYNTH, edgecolor="k", lw=0.3, label="PHEV")
    ax.set(xlabel="share of Maryland EV fleet (%)", title="EV fleet by make (Maryland 2026)")
    ax.legend(loc="lower right")
    save(fig, OUT, "fleet_by_make")

    # ---- Fig 3: assigned vs reference fleet share (fidelity) --------------
    asg = (df.ev_type.value_counts() / N * 100)
    ref = pd.Series(share)
    common = [t for t in ref.index if t in asg.index]
    fig, ax = newfig(5.2, 5)
    ax.scatter(ref[common], asg[common], s=26, color=ACCENT, edgecolor="k", lw=0.4, zorder=3)
    lim = [0, max(ref.max(), asg.max()) * 1.1]
    ax.plot(lim, lim, "--", color=GREY, lw=1)
    ax.set(xlim=lim, ylim=lim, xlabel="MD registration share (%)",
           ylabel="assigned share (%)", title="Make/model assignment fidelity")
    save(fig, OUT, "fleet_assignment_fidelity")

    # summary csv
    summ = df.groupby("make").agg(n=("ev_type", "size")).sort_values("n", ascending=False)
    summ["pct"] = (summ.n / N * 100).round(2)
    summ.to_csv(OUT / "fleet_make_summary.csv")
    print(f"[done] 3 figures + summary -> {OUT}")
    print("top makes:", summ.head(6).pct.to_dict())


if __name__ == "__main__":
    main()
