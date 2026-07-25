#!/usr/bin/env python3
"""Agent-tracked charging analysis from MATSim EVENTS (152k successful charging act-starts
with person + x/y). Joins agent demographics (income, age) and vehicle make. Produces:
  fig22_corridor_models   : EV make composition of public charging along named corridors
  fig23_who_charges_where : maps of public-charging locations colored by users' median
                            income and median age
  fig24_choice_behavior   : DCFC-vs-L2 choice + distance-from-home by income and age band
  + printed top-10 most-utilized public sites (users, income, peak hour)
All from the converged 100% baseline events. -> paper/figures/trb/"""
import sys, re, gzip, warnings
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = REPO/"paper/figures/trb"; RUNS = REPO/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"

# ---- 1. parse extracted charging act-starts ----
rx = re.compile(r'time="([\d.]+)".*person="([^"]+)".*x="([-\d.]+)" y="([-\d.]+)" actType="([^"]+)"')
rows=[]
for ln in open("/tmp/charging_actstarts.txt"):
    m=rx.search(ln)
    if m: rows.append((float(m.group(1)), m.group(2), float(m.group(3)), float(m.group(4)), m.group(5)))
ev = pd.DataFrame(rows, columns=["t","person","x","y","act"])
def ctype(a):
    if a.endswith("-L2"): return "L2"
    if a.endswith("-DCFC"): return "DCFC"
    if a.endswith("-DCFC_TESLA"): return "DCFC_TESLA"
    base=a.replace(" charging","")
    return "home" if base=="home" else ("work" if base=="work" else "other")
ev["ct"]=ev.act.map(ctype); ev["h"]=(ev.t//3600%24).astype(int)
pub = ev[ev.ct.isin(["L2","DCFC","DCFC_TESLA"])].copy()
print(f"events: {len(ev):,} charging act-starts | public: {len(pub):,}")

# ---- 2. join demographics + make ----
own = pd.read_parquet(REPO/"pipeline/data/interim/ev_owners.parquet")[["person_id","income","age"]]
import glob
f=sorted(glob.glob(str(RUNS/"baseline_pertype/ITERS/it.*/*.charging_sessions.csv")),key=lambda p:int(p.split("it.")[1].split("/")[0]))[-1]
ss=pd.read_csv(f,sep=";")
mk=ss.drop_duplicates("person_id")[["person_id","home_x","home_y"]]
# make/model from electric_vehicles.xml (sessions' ev_make column is unpopulated)
import re as _re
_vt={}
for _ln in open(REPO/"Input/vehicles/electric_vehicles.xml"):
    _m=_re.search(r'id="([^"]+)".*vehicle_type="([^"]+)"',_ln)
    if _m: _vt[_m.group(1)]=_m.group(2)
PRETTY={"model_y":"Tesla Model Y","model_3":"Tesla Model 3","model_x":"Tesla Model X","model_s":"Tesla Model S",
        "cybertruck":"Tesla Cybertruck","prius_prime":"Prius Prime","rav4_prime":"RAV4 Prime","mach_e":"Ford Mach-E",
        "eqs_eqe_eqb":"Mercedes EQ","e_tron_q4_q6_q8":"Audi e-tron","ix_i4_i5_i7":"BMW i-series","x5_x3_330e":"BMW PHEV",
        "lyriq":"Cadillac Lyriq","r1s":"Rivian R1S","ioniq_5":"Ioniq 5","equinox_ev":"Equinox EV","wrangler_4xe":"Wrangler 4xe"}
mk["ev_make"]=mk.person_id.map(_vt).map(lambda v: PRETTY.get(v, str(v).replace("_"," ").title() if v else None))
pub=pub.merge(own,left_on="person",right_on="person_id",how="left").merge(mk,left_on="person",right_on="person_id",how="left")
pub["dist_home"]=np.sqrt((pub.x-pub.home_x)**2+(pub.y-pub.home_y)**2)/1609.34
pub["age_b"]=pd.cut(pub.age,[0,34,44,54,64,200],labels=["<35","35-44","45-54","55-64","65+"])
pub["inc_q"]=pd.qcut(pub.income.rank(method="first"),4,labels=["Q1 (low)","Q2","Q3","Q4 (high)"])

# ---- 3. corridor x make ----
cor = pd.read_parquet(RUNS/"baseline/route_analysis/link_corridor.parquet")
corr_ids = set(cor.index.astype(str))
NET = REPO/"Input/network/maryland-network-pt2matsim.xml.gz"
nodes={}; mids={}
for _,el in ET.iterparse(gzip.open(NET,"rt"),events=("end",)):
    if el.tag=="node": nodes[el.get("id")]=(float(el.get("x")),float(el.get("y")))
    elif el.tag=="link":
        lid=el.get("id")
        if lid in corr_ids:
            a=nodes.get(el.get("from")); b=nodes.get(el.get("to"))
            if a and b: mids[lid]=((a[0]+b[0])/2,(a[1]+b[1])/2)
        el.clear()
cm = pd.DataFrame([(cor.loc[k,"corridor"],v[0],v[1]) for k,v in mids.items() if k in cor.index],
                  columns=["corridor","cx","cy"])
print(f"corridor links with coords: {len(cm):,}")
from scipy.spatial import cKDTree
TOPC = ["I-95","US-50","I-495 (Capital Beltway)","I-695 (Baltimore Beltway)","I-270","I-70"]
pubxy = pub[["x","y"]].values
assign = np.full(len(pub), -1)
best = np.full(len(pub), np.inf)
for i,c in enumerate(TOPC):
    pts = cm[cm.corridor==c][["cx","cy"]].values
    if not len(pts): continue
    dd,_ = cKDTree(pts).query(pubxy, k=1)
    m = (dd<1609.34) & (dd<best)          # within 1 mile, nearest corridor wins
    assign[m]=i; best[m]=dd[m]
pub["corridor"]=[TOPC[i] if i>=0 else None for i in assign]
pc = pub.dropna(subset=["corridor"])
topmk = pc.ev_make.value_counts().head(9).index.tolist()
M = pc.assign(mk=pc.ev_make.where(pc.ev_make.isin(topmk),"Other")).groupby(["corridor","mk"]).size().unstack(fill_value=0)
M = M.reindex(TOPC).apply(lambda r: r/r.sum()*100, axis=1)
fig, ax = pf.newfig(8.2, 4.4)
bottom=np.zeros(len(M))
colors=[pf.BLUE,pf.ORANGE,pf.GREEN,pf.VERM,pf.PURPLE,pf.GREY,"#B8B8B8"]
for col,c in zip(list(M.columns), colors):
    ax.bar(range(len(M)), M[col].values, 0.62, bottom=bottom, label=col, color=c, edgecolor="k", lw=0.3)
    bottom+=M[col].values
SHORT={"I-495 (Capital Beltway)":"I-495","I-695 (Baltimore Beltway)":"I-695"}
ax.set_xticks(range(len(M))); ax.set_xticklabels([SHORT.get(c,c) for c in M.index], fontsize=9)
ax.set_ylabel("share of public charging events (%)")
ax.set_title("EV make composition of public charging along major corridors (within 1 mile)")
pf.legout(ax); pf.save(fig, OUT, "fig22_corridor_models")
print("[22] corridor x make done")

# ---- 4. who charges where: income + age maps ----
tr=gpd.read_file(REPO/"pipeline/data/geo/tl_2020_24_tract.shp")[["GEOID","geometry"]]
tr["fips"]=tr.GEOID.str[:5]; cty=tr.dissolve("fips").to_crs(26985); state=cty.dissolve()
xmin,ymin,xmax,ymax=state.total_bounds
fig, axs = plt.subplots(1,2, figsize=(13,5.6))
for a,(val,ttl,cmap,vmin,vmax) in zip(axs,[
        (pub.income,"(a) Median household income of public-charging users","viridis",4,8),
        (pub.age,"(b) Median age of public-charging users","plasma",30,60)]):
    cty.plot(ax=a,color="#f5f6f7",edgecolor="#c8cdd3",linewidth=0.5)
    hb=a.hexbin(pub.x,pub.y,C=val,reduce_C_function=np.median,gridsize=60,cmap=cmap,
                mincnt=5,linewidths=0,extent=(xmin,xmax,ymin,ymax),vmin=vmin,vmax=vmax)
    state.boundary.plot(ax=a,color="#222",linewidth=1.1)
    a.set_axis_off(); a.set_aspect("equal"); a.set_title(ttl,fontsize=11)
    cb=fig.colorbar(hb,ax=a,fraction=0.035,pad=0.01); cb.ax.tick_params(labelsize=7)
    cb.set_label("income bracket (1-8)" if "income" in ttl else "age (years)",fontsize=8)
fig.suptitle("Who charges where: demographics of public-charging locations (cells with ≥5 events)",
             fontsize=12.5,fontweight="bold",y=0.99)
fig.tight_layout(rect=(0,0,1,0.96))
fig.savefig(OUT/"fig23_who_charges_where.png",dpi=300); fig.savefig(OUT/"fig23_who_charges_where.pdf")
plt.close(fig); print("[23] who-charges-where maps done")

# ---- 5. choice behavior by income & age ----
fig, ax = plt.subplots(1,3, figsize=(12.6,3.8))
d1=pub.groupby("inc_q").apply(lambda x:(x.ct!="L2").mean()*100)
ax[0].bar(range(len(d1)),d1.values,0.6,color=pf.ORANGE,edgecolor="k",lw=0.3)
ax[0].set_xticks(range(len(d1))); ax[0].set_xticklabels(d1.index,fontsize=8)
ax[0].set(ylabel="% of public events at DC-fast",title="(a) Fast-charging choice by income quartile")
d2=pub.groupby("age_b").apply(lambda x:(x.ct!="L2").mean()*100)
ax[1].bar(range(len(d2)),d2.values,0.6,color=pf.GREEN,edgecolor="k",lw=0.3)
ax[1].set_xticks(range(len(d2))); ax[1].set_xticklabels(d2.index,fontsize=8)
ax[1].set(ylabel="% of public events at DC-fast",title="(b) Fast-charging choice by age band")
d3=pub.groupby("inc_q").dist_home.median(); d4=pub.groupby("age_b").dist_home.median()
ax[2].plot(range(len(d3)),d3.values,"-o",color=pf.ORANGE,label="by income quartile")
ax[2].plot(range(len(d4)),d4.values,"-s",color=pf.GREEN,label="by age band")
ax[2].set_xticks(range(max(len(d3),len(d4))))
ax[2].set_xticklabels([f"{a}\n{b}" for a,b in zip(list(d1.index)+[""],list(d2.index))][:max(len(d3),len(d4))],fontsize=7)
ax[2].set(ylabel="median distance from home (mi)",title="(c) How far from home agents charge")
ax[2].legend(fontsize=8)
for a in ax: a.grid(alpha=0.25)
fig.suptitle("Charging-site choice behavior by demographic group (public events, tracked agents)",
             fontsize=12,fontweight="bold",y=1.02)
fig.tight_layout(rect=(0,0,1,0.97))
fig.savefig(OUT/"fig24_choice_behavior.png",dpi=300); fig.savefig(OUT/"fig24_choice_behavior.pdf")
plt.close(fig); print("[24] choice behavior done")

# ---- 6. top utilized sites ----
pub["gx"]=(pub.x//500*500); pub["gy"]=(pub.y//500*500)
top=pub.groupby(["gx","gy"]).agg(events=("person","size"),users=("person","nunique"),
    med_inc=("income","median"),med_age=("age","median"),
    peak_h=("h",lambda s:s.mode().iloc[0]),dcfc=("ct",lambda s:(s!="L2").mean()*100)).nlargest(10,"events")
print("\nTOP-10 public charging sites (500m cells):")
print(top.round(1).to_string())
