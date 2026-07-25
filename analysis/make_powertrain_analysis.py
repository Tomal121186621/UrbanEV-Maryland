#!/usr/bin/env python3
"""Agent-tracked PUBLIC-charging analysis rebuilt from ACTUAL charging sessions
(15.charging_sessions.csv — successful plug-ins only; the earlier actstart-event
version silently included ~48k failed/incompatible attempts, e.g. PHEVs whose
optimistic plan tag pointed at a Tesla Supercharger; the handler rejects those).
Coordinates joined from actstart events by (person, activity, start-time).
  fig22_corridor_models   : corridor stacks by CLASS — PHEV / Tesla BEV / other BEV
  fig23_who_charges_where : income + age maps of public-charging users
  fig24_choice_behavior   : DC-fast choice + distance-from-home by income/age band
  fig25_powertrain_map    : PHEV-share map + class split by charger type
-> paper/figures/trb/"""
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

# ---- 1. actual sessions + coordinates from actstart events ----
ss = pd.read_csv(RUNS/"baseline_pertype/ITERS/it.15/15.charging_sessions.csv", sep=";")
pub = ss[ss.charger_type.isin(["L2","DCFC","DCFC_TESLA"])].copy()
rx = re.compile(r'time="([\d.]+)".*person="([^"]+)".*x="([-\d.]+)" y="([-\d.]+)" actType="([^"]+)"')
rows=[]
for ln in open("/tmp/charging_actstarts.txt"):
    m=rx.search(ln)
    if m: rows.append((float(m.group(1)),m.group(2),float(m.group(3)),float(m.group(4)),m.group(5)))
evt = pd.DataFrame(rows, columns=["t","person","x","y","act"])
pub = pub.merge(evt, left_on=["person_id","activity_type","time_start_s"],
                right_on=["person","act","t"], how="left")
# fallback: per-person nearest actstart within 2 h
miss = pub.x.isna()
if miss.any():
    ev_by_p = {p:g[["t","x","y"]].values for p,g in evt.groupby("person")}
    xs=[]; ys=[]
    for pid,t0 in pub.loc[miss,["person_id","time_start_s"]].values:
        g = ev_by_p.get(pid)
        if g is None: xs.append(np.nan); ys.append(np.nan); continue
        i = np.argmin(np.abs(g[:,0]-t0))
        if abs(g[i,0]-t0) <= 7200: xs.append(g[i,1]); ys.append(g[i,2])
        else: xs.append(np.nan); ys.append(np.nan)
    pub.loc[miss,"x"]=xs; pub.loc[miss,"y"]=ys
print(f"public sessions: {len(pub):,} | with coords: {pub.x.notna().mean()*100:.1f}%")
pub = pub.dropna(subset=["x","y"]).copy()

# ---- 2. demographics, class, distances ----
own = pd.read_parquet(REPO/"pipeline/data/interim/ev_owners.parquet")[["person_id","income","age"]]
pub = pub.merge(own, on="person_id", how="left")
pub["cls"]=np.where(pub.ev_type=="PHEV","PHEV",
             np.where(pub.ev_model.astype(str).str.startswith(("model_","cybertruck")),"Tesla BEV","Other BEV"))
pub["dist_home"]=np.sqrt((pub.x-pub.home_x)**2+(pub.y-pub.home_y)**2)/1609.34
pub["h"]=(pub.time_start_s//3600%24).astype(int)
pub["age_b"]=pd.cut(pub.age,[0,34,44,54,64,200],labels=["<35","35-44","45-54","55-64","65+"])
pub["inc_q"]=pd.qcut(pub.income.rank(method="first"),4,labels=["Q1 (low)","Q2","Q3","Q4 (high)"])
fleet = pd.read_parquet(REPO/"pipeline/data/interim/ev_owners.parquet")
if "ev_powertrain" in fleet.columns:
    fs = fleet.ev_powertrain.value_counts(normalize=True).get("PHEV",np.nan)*100
else: fs=np.nan
phev_pub=(pub.cls=="PHEV").mean()*100
print(f"PHEV: {phev_pub:.0f}% of public sessions vs {fs:.0f}% of fleet (x{phev_pub/fs:.1f})")
print(pub.groupby("charger_type").cls.value_counts(normalize=True).unstack().mul(100).round(0).to_string())
top_phev = pub[pub.cls=="PHEV"].ev_model.value_counts().head(3).index.tolist()
print("top PHEV models at public chargers:", top_phev)

# ---- 3. fig22: corridor x class, explicit % ----
cor = pd.read_parquet(RUNS/"baseline/route_analysis/link_corridor.parquet"); corr_ids=set(cor.index.astype(str))
nodes={}; mids={}
for _,el in ET.iterparse(gzip.open(REPO/"Input/network/maryland-network-pt2matsim.xml.gz","rt"),events=("end",)):
    if el.tag=="node": nodes[el.get("id")]=(float(el.get("x")),float(el.get("y")))
    elif el.tag=="link":
        lid=el.get("id")
        if lid in corr_ids:
            a=nodes.get(el.get("from")); b=nodes.get(el.get("to"))
            if a and b: mids[lid]=((a[0]+b[0])/2,(a[1]+b[1])/2)
        el.clear()
cm=pd.DataFrame([(cor.loc[k,"corridor"],v[0],v[1]) for k,v in mids.items()],columns=["corridor","cx","cy"])
from scipy.spatial import cKDTree
TOPC=["I-95","US-50","I-495 (Capital Beltway)","I-695 (Baltimore Beltway)","I-270","I-70"]
SHORT={"I-495 (Capital Beltway)":"I-495","I-695 (Baltimore Beltway)":"I-695"}
assign=np.full(len(pub),-1); best=np.full(len(pub),np.inf)
pxy=pub[["x","y"]].values
for i,c in enumerate(TOPC):
    pts=cm[cm.corridor==c][["cx","cy"]].values
    if not len(pts): continue
    dd,_=cKDTree(pts).query(pxy,k=1)
    m=(dd<1609.34)&(dd<best); assign[m]=i; best[m]=dd[m]
pub["corridor"]=[TOPC[i] if i>=0 else None for i in assign]
pc=pub.dropna(subset=["corridor"])
print(f"sessions within 1 mi of a top corridor: {len(pc):,}")
M=pc.groupby(["corridor","cls"]).size().unstack(fill_value=0).reindex(TOPC)
M=M[["PHEV","Other BEV","Tesla BEV"]].apply(lambda r:r/r.sum()*100,axis=1)
cols={"PHEV":pf.VERM,"Other BEV":pf.BLUE,"Tesla BEV":pf.GREY}
fig,ax=pf.newfig(8.4,4.6)
bottom=np.zeros(len(M))
for cl in ["PHEV","Other BEV","Tesla BEV"]:
    v=M[cl].values
    ax.bar(range(len(M)),v,0.62,bottom=bottom,label=cl,color=cols[cl],edgecolor="k",lw=0.4)
    for i,(b_,vv) in enumerate(zip(bottom,v)):
        if vv>6: ax.text(i,b_+vv/2,f"{vv:.0f}%",ha="center",va="center",fontsize=9,
                         color="white" if cl!="Tesla BEV" else "black",fontweight="bold")
    bottom+=v
ax.set_xticks(range(len(M))); ax.set_xticklabels([SHORT.get(c,c) for c in M.index],fontsize=9.5)
ax.set_ylabel("share of public charging sessions (%)"); ax.set_ylim(0,104)
ax.set_title("Public charging along major corridors, by powertrain class (within 1 mile)")
pf.legout(ax); pf.save(fig,OUT,"fig22_corridor_models")
print("[22] done")

# ---- 4. fig23: who charges where (income, age) ----
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
fig.suptitle("Who charges where: demographics of public charging sessions (cells with ≥5 sessions)",
             fontsize=12.5,fontweight="bold",y=0.99)
fig.tight_layout(rect=(0,0,1,0.96))
fig.savefig(OUT/"fig23_who_charges_where.png",dpi=300); fig.savefig(OUT/"fig23_who_charges_where.pdf")
plt.close(fig); print("[23] done")

# ---- 5. fig24: choice behavior ----
fig, ax = plt.subplots(1,3, figsize=(12.6,3.8))
d1=pub.groupby("inc_q").apply(lambda g:(g.charger_type!="L2").mean()*100)
ax[0].bar(range(len(d1)),d1.values,0.6,color=pf.ORANGE,edgecolor="k",lw=0.3)
ax[0].set_xticks(range(len(d1))); ax[0].set_xticklabels(d1.index,fontsize=8)
ax[0].set(ylabel="% of public sessions at DC-fast",title="(a) Fast-charging choice by income quartile")
d2=pub.groupby("age_b").apply(lambda g:(g.charger_type!="L2").mean()*100)
ax[1].bar(range(len(d2)),d2.values,0.6,color=pf.GREEN,edgecolor="k",lw=0.3)
ax[1].set_xticks(range(len(d2))); ax[1].set_xticklabels(d2.index,fontsize=8)
ax[1].set(ylabel="% of public sessions at DC-fast",title="(b) Fast-charging choice by age band")
d3=pub.groupby("inc_q").dist_home.median(); d4=pub.groupby("age_b").dist_home.median()
ax[2].plot(range(len(d3)),d3.values,"-o",color=pf.ORANGE,label="by income quartile")
ax[2].plot(range(len(d4)),d4.values,"-s",color=pf.GREEN,label="by age band")
ax[2].set_xticks(range(max(len(d3),len(d4))))
ax[2].set_xticklabels([f"{a}\n{b}" for a,b in zip(list(d1.index)+[""],list(d2.index))][:max(len(d3),len(d4))],fontsize=7)
ax[2].set(ylabel="median distance from home (mi)",title="(c) How far from home agents charge")
ax[2].legend(fontsize=8)
for a in ax: a.grid(alpha=0.25)
fig.suptitle("Charging-site choice behavior by demographic group (successful public sessions)",
             fontsize=12,fontweight="bold",y=1.02)
fig.tight_layout(rect=(0,0,1,0.97))
fig.savefig(OUT/"fig24_choice_behavior.png",dpi=300); fig.savefig(OUT/"fig24_choice_behavior.pdf")
plt.close(fig); print("[24] done")

# ---- 6. fig25: PHEV-share map + class by charger type ----
fig,axs=plt.subplots(1,2,figsize=(13.6,5.6),gridspec_kw={"width_ratios":[1.9,1]})
a=axs[0]
cty.plot(ax=a,color="#f5f6f7",edgecolor="#c8cdd3",linewidth=0.5)
hb=a.hexbin(pub.x,pub.y,C=(pub.cls=="PHEV").astype(float),reduce_C_function=np.mean,gridsize=55,
            cmap="RdBu_r",vmin=0.2,vmax=0.9,mincnt=8,linewidths=0,extent=(xmin,xmax,ymin,ymax))
state.boundary.plot(ax=a,color="#222",linewidth=1.1)
a.set_axis_off(); a.set_aspect("equal")
a.set_title("(a) PHEV share of public charging sessions (red = PHEV-dominated, blue = BEV)",fontsize=11)
cb=fig.colorbar(hb,ax=a,fraction=0.03,pad=0.01); cb.set_label("PHEV share of sessions",fontsize=9)
b=axs[1]
S=pub.groupby("charger_type").cls.value_counts(normalize=True).unstack().mul(100).reindex(["L2","DCFC","DCFC_TESLA"])
bottom=np.zeros(len(S))
for cl in ["PHEV","Other BEV","Tesla BEV"]:
    v=S[cl].fillna(0).values
    b.bar(range(len(S)),v,0.6,bottom=bottom,label=cl,color=cols[cl],edgecolor="k",lw=0.4)
    for i,(b_,vv) in enumerate(zip(bottom,v)):
        if vv>7: b.text(i,b_+vv/2,f"{vv:.0f}%",ha="center",va="center",fontsize=9,
                        color="white" if cl!="Tesla BEV" else "black",fontweight="bold")
    bottom+=v
b.set_xticks(range(len(S))); b.set_xticklabels(["L2","DCFC","Tesla SC"],fontsize=9)
b.set_ylabel("share of sessions (%)"); b.set_ylim(0,104)
b.set_title("(b) Powertrain class by charger type",fontsize=11)
b.legend(fontsize=8,loc="upper center",bbox_to_anchor=(0.5,-0.09),ncol=3,frameon=False)
fig.suptitle(f"Who uses public charging: PHEVs make {phev_pub:.0f}% of public sessions vs {fs:.0f}% of the fleet "
             f"(x{phev_pub/fs:.1f} over-represented)",fontsize=12.5,fontweight="bold",y=1.0)
fig.tight_layout(rect=(0,0.02,1,0.95))
fig.savefig(OUT/"fig25_powertrain_map.png",dpi=300); fig.savefig(OUT/"fig25_powertrain_map.pdf")
plt.close(fig); print("[25] done")

# ---- 7. top sites (sessions) ----
pub["gx"]=(pub.x//500*500); pub["gy"]=(pub.y//500*500)
top=pub.groupby(["gx","gy"]).agg(sessions=("person_id","size"),users=("person_id","nunique"),
    med_inc=("income","median"),med_age=("age","median"),
    peak_h=("h",lambda s:s.mode().iloc[0]),dcfc=("charger_type",lambda s:(s!="L2").mean()*100),
    phev=("cls",lambda s:(s=="PHEV").mean()*100)).nlargest(10,"sessions")
print("\nTOP-10 public charging sites (500m cells, successful sessions):")
print(top.round(1).to_string())
