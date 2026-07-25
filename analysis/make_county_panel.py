#!/usr/bin/env python3
"""County-wise validation — COMPLETE: per-county TVD between synthetic and independent ACS
for ALL six comparable attributes (age, income, household size, vehicles, tenure, dwelling).
Heatmap (counties sorted by population x attributes), annotated; plus mean row/col.
-> paper/figures/validation_trb/fig_val_county.png"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")
REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
ACS = REPO/"pipeline/data/reference/acs2024"; OUT = REPO/"paper/figures/validation_trb"
COUNTY = {"24001":"Allegany","24003":"Anne Arundel","24005":"Baltimore Co.","24009":"Calvert",
 "24011":"Caroline","24013":"Carroll","24015":"Cecil","24017":"Charles","24019":"Dorchester",
 "24021":"Frederick","24023":"Garrett","24025":"Harford","24027":"Howard","24029":"Kent",
 "24031":"Montgomery","24033":"Prince George's","24035":"Queen Anne's","24037":"St. Mary's",
 "24039":"Somerset","24041":"Talbot","24043":"Washington","24045":"Wicomico",
 "24047":"Worcester","24510":"Baltimore City"}

def acs_cty(table):
    d = pd.read_csv(ACS/f"acsdt5y2024-{table}.dat", sep="|")
    d = d[d.GEO_ID.astype(str).str.startswith("0500000US24")].copy()
    d["fips"] = d.GEO_ID.str[-5:]
    return d.set_index("fips")
def cells(row, t, nums): return sum(row[f"{t}_E{n:03d}"] for n in nums)

b01 = acs_cty("b01001"); b19 = acs_cty("b19001"); b11 = acs_cty("b11016")
b25 = acs_cty("b25003"); b24 = acs_cty("b25024"); b08 = acs_cty("b08201")
def acs_dist(fips, attr):
    if attr=="age_b":
        r=b01.loc[fips]
        return pd.Series({"<25":cells(r,"B01001",range(3,11))+cells(r,"B01001",range(27,35)),
            "25-34":cells(r,"B01001",[11,12])+cells(r,"B01001",[35,36]),
            "35-44":cells(r,"B01001",[13,14])+cells(r,"B01001",[37,38]),
            "45-54":cells(r,"B01001",[15,16])+cells(r,"B01001",[39,40]),
            "55-64":cells(r,"B01001",[17,18,19])+cells(r,"B01001",[41,42,43]),
            "65+":cells(r,"B01001",range(20,26))+cells(r,"B01001",range(44,50))})
    if attr=="hh_income_detailed":
        r=b19.loc[fips]
        return pd.Series({"1":cells(r,"B19001",[2,3]),"2":cells(r,"B19001",[4,5]),
            "3":cells(r,"B19001",[6,7]),"4":cells(r,"B19001",[8,9,10]),
            "5":cells(r,"B19001",[11,12]),"6":r["B19001_E013"],
            "7":cells(r,"B19001",[14,15]),"8":cells(r,"B19001",[16,17])})
    if attr=="hhsize":
        r=b11.loc[fips]
        return pd.Series({"1":r["B11016_E010"],"2":r["B11016_E003"]+r["B11016_E011"],
            "3":r["B11016_E004"]+r["B11016_E012"],"4":r["B11016_E005"]+r["B11016_E013"],
            "5":r["B11016_E006"]+r["B11016_E014"],"6":r["B11016_E007"]+r["B11016_E015"],
            "7":r["B11016_E008"]+r["B11016_E016"]})
    if attr=="numvehicle":
        r=b08.loc[fips]
        return pd.Series({"0":r["B08201_E002"],"1":r["B08201_E003"],"2":r["B08201_E004"],
                          "3":r["B08201_E005"],"4":r["B08201_E006"]})
    if attr=="home_ownership":
        r=b25.loc[fips]; return pd.Series({"1":r["B25003_E002"],"2":r["B25003_E003"]})
    if attr=="home_type":
        r=b24.loc[fips]
        return pd.Series({"1":r["B25024_E002"],"2":r["B25024_E003"],
                          "3":cells(r,"B25024",range(4,10)),"4":cells(r,"B25024",[10,11])})

syn = pd.read_parquet(REPO/"pipeline/data/interim/synth_person.parquet",
        columns=["home_county","age","hh_income_detailed","hhsize","numvehicle","home_ownership","home_type"])
syn["fips"]=syn.home_county.astype(str).str.zfill(5)
syn["age_b"]=pd.cut(syn.age,[0,24,34,44,54,64,200],labels=["<25","25-34","35-44","45-54","55-64","65+"]).astype(str)
for c in ["hh_income_detailed","hhsize","numvehicle","home_ownership","home_type"]:
    syn[c]=pd.to_numeric(syn[c],errors="coerce").round().astype("Int64").astype(str)
syn["hhsize_c"]=syn.hhsize.replace({"8":"7"})                # 7+ bucket
syn["numvehicle_c"]=syn.numvehicle.replace({str(k):"4" for k in range(4,10)})  # 4+ bucket
syn["hw"]=1.0/pd.to_numeric(syn.hhsize,errors="coerce").clip(lower=1)

ATTRS=[("age_b","Age","p","age_b"),("hh_income_detailed","Income","h","hh_income_detailed"),
       ("hhsize","HH size","h","hhsize_c"),("numvehicle","Vehicles","h","numvehicle_c"),
       ("home_ownership","Tenure","h","home_ownership"),("home_type","Dwelling","h","home_type")]
pop_order = b01["B01001_E001"].sort_values(ascending=False).index.tolist()
M = np.zeros((len(pop_order), len(ATTRS)))
for j,(attr,lab,uni,scol) in enumerate(ATTRS):
    for i_,f in enumerate(pop_order):
        a = acs_dist(f, attr).astype(float); a = a/a.sum()
        s = syn[syn.fips==f]
        if attr=="home_ownership": s = s[s.home_ownership.isin(["1","2"])]
        if attr=="home_type": s = s[s.home_type!="5"]
        w = None if uni=="p" else s.hw
        g = s.groupby(scol).size() if uni=="p" else s.groupby(scol).hw.sum()
        g = g/g.sum()
        idx = sorted(set(a.index)|set(g.index), key=str)
        M[i_,j] = 0.5*np.abs(a.reindex(idx,fill_value=0).values - g.reindex(idx,fill_value=0).values).sum()

fig, ax = plt.subplots(figsize=(8.6, 10.5))
im = ax.imshow(M, cmap="YlOrRd", vmin=0, vmax=0.30, aspect="auto")
ax.set_xticks(range(len(ATTRS))); ax.set_xticklabels([l for _,l,_,_ in ATTRS], fontsize=10)
ax.set_yticks(range(len(pop_order))); ax.set_yticklabels([COUNTY.get(f,f) for f in pop_order], fontsize=8.5)
for i_ in range(M.shape[0]):
    for j in range(M.shape[1]):
        ax.text(j, i_, f"{M[i_,j]:.2f}", ha="center", va="center", fontsize=7,
                color="white" if M[i_,j]>0.18 else "black")
cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02); cb.set_label("TVD (synthetic vs ACS)", fontsize=9)
colmean = M.mean(axis=0)
ax.set_title("County-level validation vs independent Census ACS — per-county TVD, all attributes\n"
             + "mean TVD by attribute:  " + "  ".join(f"{l} {m:.2f}" for (_,l,_,_),m in zip(ATTRS,colmean)),
             fontsize=11, fontweight="bold")
fig.tight_layout()
fig.savefig(OUT/"fig_val_county.png", dpi=300); fig.savefig(OUT/"fig_val_county.pdf")
plt.close(fig)
print("mean TVD by attribute:", {l: round(m,3) for (_,l,_,_),m in zip(ATTRS,colmean)})
print("overall mean TVD:", round(M.mean(),3), " worst county:", COUNTY.get(pop_order[int(np.argmax(M.mean(1)))]))
print("-> fig_val_county.png")
