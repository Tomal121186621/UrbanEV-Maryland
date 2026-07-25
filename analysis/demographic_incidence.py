#!/usr/bin/env python3
"""Who bears the burden — demographic incidence of EV road-funding instruments, using ALL
per-agent characteristics (income, age, employment, dwelling, tenure, home-charger access,
powertrain, household size, workers). Effective tax rate (burden / income) by category.
Also a 'representative drivers' comparison. -> paper/figures/."""
import sys, gzip, re
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline"))
from src import labels as L
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
T = REPO / "paper/tables"; FIG = REPO / "paper/figures"

# ---- per-agent home-charger access from the plans file (stream; cache) ----
hc_path = T / "per_agent_homecharger.parquet"
if hc_path.exists():
    hc = pd.read_parquet(hc_path)
else:
    plans = REPO / "Input/population/plans_maryland_ev_2026.xml.gz"
    pid, power, cur = [], [], None
    pr = re.compile(r'<person id="([^"]+)"'); ar = re.compile(r'homeChargerPower[^>]*>([^<]+)<')
    with gzip.open(plans, "rt") as f:
        for ln in f:
            mp = pr.search(ln)
            if mp:
                cur = mp.group(1)
            elif cur and "homeChargerPower" in ln:
                ma = ar.search(ln)
                if ma:
                    pid.append(cur); power.append(float(ma.group(1))); cur = None
    hc = pd.DataFrame({"person_id": pid, "home_charger_kw": power})
    hc["has_home_charger"] = hc.home_charger_kw > 0
    hc.to_parquet(hc_path)
print(f"home-charger access: {hc.has_home_charger.mean()*100:.1f}% of {len(hc):,}")

# ---- merge burdens + demographics + home charger ----
b = pd.read_parquet(T / "per_agent_burdens.parquet")
ev = pd.read_parquet(REPO / "pipeline/data/interim/ev_owners.parquet").drop(columns=["ev_powertrain"])
d = b.merge(ev, left_on="vehicle_id", right_on="person_id", how="left").merge(hc, on="person_id", how="left")
d["inc"] = d["income_usd"].astype(float)

# derived categorical bands
d["age_band"] = pd.cut(d.age.astype(float), [0, 25, 35, 45, 55, 65, 120],
                       labels=["<25", "25–34", "35–44", "45–54", "55–64", "65+"])
d["hhsize_b"] = pd.to_numeric(d.hhsize, errors="coerce").clip(1, 5).map({1: "1", 2: "2", 3: "3", 4: "4", 5: "5+"})
emp = {"0": "Worker", "1": "Retired", "2": "Volunteer", "3": "Homemaker", "4": "Unemp.", "5": "Unemp.", "6": "Student", "7": "Disabled"}
d["emp"] = d.employment_status.astype(str).map(emp)
d["dwelling"] = d.home_type.astype(str).map({"1": "SF detached", "2": "SF attached", "3": "Apt/Condo", "4": "Mobile", "5": "Other"})
d["tenure"] = d.home_ownership.astype(str).map({"1": "Own", "2": "Rent", "3": "Other"})
d["hcacc"] = d.has_home_charger.map({True: "Home charger", False: "No home charger"})

INST = [("flat_fee", "Flat fee ($224)", pf.VERM),
        ("md_actual", "MD fee ($125/$100)", pf.ORANGE),
        ("ruc", "Flat RUC (per-mile)", pf.GREEN),
        ("T1_state_public_5c", "Charging: public +5¢", pf.BLUE)]

# effective rate (sum burden / sum income) by category
def eff(gcol, order):
    g = d.dropna(subset=[gcol])
    out = {}
    for k, lab, c in INST:
        s = g.groupby(gcol).apply(lambda x: x[k].sum() / x.inc.sum() * 100)
        out[lab] = s.reindex(order)
    return pd.DataFrame(out).reindex(order)

PANELS = [("oct", [1,2,3,4,5,6,7,8], "Income octile (low→high)"),
          ("age_band", ["<25","25–34","35–44","45–54","55–64","65+"], "Age"),
          ("emp", ["Worker","Retired","Homemaker","Student","Disabled","Unemp."], "Employment"),
          ("dwelling", ["SF detached","SF attached","Apt/Condo","Mobile"], "Dwelling type"),
          ("tenure", ["Own","Rent","Other"], "Tenure"),
          ("hcacc", ["Home charger","No home charger"], "Home-charger access"),
          ("ev_powertrain", ["BEV","PHEV"], "Powertrain"),
          ("hhsize_b", ["1","2","3","4","5+"], "Household size")]

fig, axs = plt.subplots(4, 2, figsize=(11, 13)); axs = axs.ravel()
for ax, (col, order, title) in zip(axs, PANELS):
    tab = eff(col, order)
    x = np.arange(len(order)); w = 0.2
    for j, (k, lab, c) in enumerate(INST):
        ax.bar(x + (j - 1.5) * w, tab[lab].values, w, color=c, edgecolor="k", lw=0.25)
    ax.set_xticks(x); ax.set_xticklabels([str(o) for o in order], rotation=20, ha="right", fontsize=8)
    ax.set_title(title, fontsize=11); ax.set_ylabel("eff. rate (% income)", fontsize=9)
    ax.grid(axis="y", alpha=0.25)
h = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in INST]
fig.legend(h, [lab for _, lab, _ in INST], loc="lower center", ncol=4, fontsize=10, frameon=False, bbox_to_anchor=(0.5, -0.01))
fig.suptitle("Demographic incidence: effective tax rate by driver characteristic", fontsize=13, fontweight="bold", y=1.005)
fig.tight_layout(rect=(0, 0.03, 1, 0.99))
fig.savefig(FIG / "demographic_incidence.png", dpi=300, bbox_inches="tight")
fig.savefig(FIG / "demographic_incidence.pdf", bbox_inches="tight")
plt.close(fig); print("-> demographic_incidence.png")

# ---- representative drivers (GROUP MEANS over each archetype, not a single noisy agent) ----
arche = {
    "High-income homeowner BEV\n(SF, home charger)": (d.tenure.eq("Own") & d.has_home_charger & d.ev_powertrain.eq("BEV") & (d.oct >= 7)),
    "Low-income renter, no home charger\n(Apt, public-reliant)": (d.tenure.eq("Rent") & ~d.has_home_charger & (d.oct <= 3)),
    "Mid-income PHEV commuter\n(works, charges at work)": (d.ev_powertrain.eq("PHEV") & d.charge_at_work.astype(str).eq("1") & d.oct.between(4, 6)),
    "Retired homeowner BEV\n(low mileage)": (d.emp.eq("Retired") & d.tenure.eq("Own") & d.ev_powertrain.eq("BEV")),
}
rows = []
for name, m in arche.items():
    s = d[m]
    if not len(s): continue
    rows.append(dict(driver=name, n=len(s), income=int(s.inc.median()),
                     **{lab: round(float(s[k].mean()), 0) for k, lab, _ in INST}))
rd = pd.DataFrame(rows); rd.to_csv(T / "representative_drivers.csv", index=False)
fig, ax = pf.newfig(8.2, 4.2)
x = np.arange(len(rd)); w = 0.2
for j, (k, lab, c) in enumerate(INST):
    ax.bar(x + (j - 1.5) * w, rd[lab].values, w, color=c, edgecolor="k", lw=0.3, label=lab)
ax.set_xticks(x); ax.set_xticklabels([n.split("\n")[0] for n in rd.driver], rotation=12, ha="right", fontsize=8)
ax.set_ylabel("annual burden ($/yr)"); ax.set_title("A tale of representative drivers: annual bill by instrument")
pf.legout(ax); pf.save(fig, FIG, "representative_drivers")
print("-> representative_drivers.png"); print(rd.to_string(index=False))
