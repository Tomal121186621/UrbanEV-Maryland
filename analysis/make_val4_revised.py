#!/usr/bin/env python3
"""REVISED val4_ev_assignment panel -> validation_package/panels.
Layout: (a) county EV totals vs MVA, (b) county BEV share vs MVA,
        (c) LARGE county x make/model composition heatmap (replaces income panel).
"""
import sys, re
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, "/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB/UrbanEV-Maryland/analysis")
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = ROOT/"paper/validation_package/panels"

own = pd.read_parquet(ROOT/"pipeline/data/interim/ev_owners.parquet")
own["fips"] = own.home_county.astype(float).astype(int)
mva = pd.read_csv(ROOT/"pipeline/data/reference/mva/MDOT_MVA_Electric_and_Plug-in_Hybrid_Vehicle_Registrations_by_County_as_of_each_month_end_20260313.csv")
mva["Count"] = mva.Count.astype(str).str.replace(",","").astype(int)
mva = mva[mva.Year_Month==mva.Year_Month.max()]
MD = {"ALLEGANY":24001,"ANNE ARUNDEL":24003,"BALTIMORE":24005,"CALVERT":24009,"CAROLINE":24011,
      "CARROLL":24013,"CECIL":24015,"CHARLES":24017,"DORCHESTER":24019,"FREDERICK":24021,
      "GARRETT":24023,"HARFORD":24025,"HOWARD":24027,"KENT":24029,"MONTGOMERY":24031,
      "PRINCE GEORGES":24033,"QUEEN ANNES":24035,"SAINT MARYS":24037,"SOMERSET":24039,
      "TALBOT":24041,"WASHINGTON":24043,"WICOMICO":24045,"WORCESTER":24047,"BALTIMORE CITY":24510}
NAME = {v:k.title().replace("Georges","George's").replace("Marys","Mary's").replace("Annes","Anne's") for k,v in MD.items()}
mva["fips"] = mva.County.str.upper().str.replace("'","").str.replace("ST.","SAINT",regex=False).str.strip().map(MD)
mtot = mva.groupby("fips").Count.sum()
mbev = mva[mva.Fuel_Category=="Electric"].groupby("fips").Count.sum()
stot = own.groupby("fips").size()
sbev = own[own.ev_powertrain=="BEV"].groupby("fips").size()

# model per person (full fleet, dedup)
vt = {}
for ln in open(ROOT/"Input/vehicles/electric_vehicles.xml"):
    m = re.search(r'id="([^"]+)".*vehicle_type="([^"]+)"', ln)
    if m: vt[m.group(1)] = m.group(2)
own["model"] = own.person_id.map(vt)
PRETTY = {"model_y":"Model Y","model_3":"Model 3","cybertruck":"Cybertruck","ix_i4_i5_i7":"BMW i-series",
          "rav4_prime":"RAV4 Prime","x5_x3_330e_530e":"BMW PHEV","mustang_mach_e":"Mach-E","lyriq":"Lyriq",
          "r1s":"R1S","eqs_eqe_eqb":"Mercedes EQ","prius_prime":"Prius Prime","e_tron_q4_q6_q8":"Audi e-tron",
          "equinox_ev":"Equinox EV","wrangler_4xe":"Wrangler 4xe","ioniq_5":"Ioniq 5","model_x":"Model X",
          "nx_rx_phev":"Lexus NX/RX PHEV","xc60_s60_s90_phev":"Volvo XC60/S60/S90","2_3_4":"Polestar 2/3/4",
          "grand_cherokee_4xe":"Grand Cherokee 4xe","prologue":"Prologue","model_s":"Model S"}
top = own.model.value_counts().head(6).index.tolist()
PHEVS = set(pd.read_csv(ROOT/"research/phev_gas_fallback_costs.csv").ev_type)
def lab(row):
    m = row.model
    if m in top: return PRETTY.get(m, str(m).replace("_"," ").title())
    return "Other PHEV" if m in PHEVS else "Other BEV"
own["mlab"] = own.apply(lab, axis=1)
cols_order = [PRETTY.get(m, str(m).replace("_"," ").title()) for m in top] + ["Other BEV","Other PHEV"]
H = own.groupby(["fips","mlab"]).size().unstack(fill_value=0)
H = H.div(H.sum(1), axis=0).mul(100)[cols_order]
H = H.loc[stot.sort_values(ascending=False).index]  # counties by fleet size

fig, cx = plt.subplots(figsize=(11, 8))
ms = own.model.value_counts(normalize=True).mul(100).head(22)
labels = [PRETTY.get(m, str(m).replace("_"," ").title()) for m in ms.index]
PHEVS = set(pd.read_csv(ROOT/"research/phev_gas_fallback_costs.csv").ev_type)
cols = [pf.ORANGE if m in PHEVS else pf.BLUE for m in ms.index]
y = np.arange(len(ms))[::-1]
cx.barh(y, ms.values, height=0.72, color=cols, edgecolor="k", lw=0.4)
for yi, v in zip(y, ms.values):
    cx.text(v+0.15, yi, f"{v:.1f}", va="center", fontsize=9)
cx.set_yticks(y); cx.set_yticklabels(labels, fontsize=10.5)
cx.set_xlabel("share of Maryland EV fleet (%)", fontsize=11)
cx.set_xlim(0, ms.max()*1.12)
cx.grid(axis="x", alpha=0.25)
from matplotlib.patches import Patch
cx.legend(handles=[Patch(fc=pf.BLUE, ec="k", label="BEV"),
                   Patch(fc=pf.ORANGE, ec="k", label="PHEV")], fontsize=10, loc="lower right")
cx.set_title("Assigned EV fleet composition (MVA market shares), Maryland 2026", fontsize=13, fontweight="bold", pad=8)
fig.savefig(OUT/"val4_ev_assignment.png", dpi=300, bbox_inches="tight")
fig.savefig(OUT/"val4_ev_assignment.pdf", bbox_inches="tight")
plt.close(fig); print("val4 fleet-composition figure done")
