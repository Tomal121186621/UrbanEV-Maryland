#!/usr/bin/env python3
"""T5/T6 VMT-toll analysis: revenue from personMoney events; diversion from
tolled-link VMT vs baseline. Streams it.50 events of gasfb4, sw_T5, sw_T6."""
import gzip, re, sys
import pandas as pd
import xml.etree.ElementTree as ET

ROOT="/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB"
R=f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
S,D=4,3

def toll_links(path):
    ids=set()
    for ln in open(path):
        m=re.search(r'<link id="([^"]+)"',ln)
        if m: ids.add(m.group(1))
    return ids
T5=toll_links(f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/sample_25pct/toll_T5_corridors.xml")
T6=toll_links(f"{ROOT}/UrbanEV-Maryland/scenarios/maryland/sample_25pct/toll_T6_interstates.xml")
# link lengths
length={}
for _,el in ET.iterparse(gzip.open(f"{ROOT}/Input/network/maryland-network-pt2matsim.xml.gz","rt"),events=("end",)):
    if el.tag=="link":
        lid=el.get("id")
        if lid in T5 or lid in T6: length[lid]=float(el.get("length"))
        el.clear()
print(f"toll links: T5 {len(T5)} T6 {len(T6)}", flush=True)

rx_link=re.compile(r'type="left link".*link="([^"]+)"')
rx_money=re.compile(r'type="personMoney".*amount="(-?[\d.eE+-]+)"')
def scan(run):
    vmt5=vmt6=0.0; money=0.0; n=0
    f=f"{R}/{run}/ITERS/it.50/50.events.xml.gz"
    for ln in gzip.open(f,"rt"):
        if 'left link' in ln:
            m=rx_link.search(ln)
            if m:
                l=m.group(1)
                if l in T6:
                    vmt6+=length.get(l,0)
                    if l in T5: vmt5+=length.get(l,0)
                elif l in T5: vmt5+=length.get(l,0)
        elif 'personMoney' in ln:
            m=rx_money.search(ln)
            if m: money+=abs(float(m.group(1))); n+=1
    return vmt5/1609.34, vmt6/1609.34, money, n

res={}
for run in ["gasfb4_baseline_25pct","sw_T5","sw_T6"]:
    res[run]=scan(run)
    print(run, "corridorVMT %.0f interstateVMT %.0f toll$ %.0f (n=%d)"%res[run], flush=True)

b5,b6,_,_=res["gasfb4_baseline_25pct"]
t5v,_,t5m,_=res["sw_T5"]
_,t6v,t6m,_=res["sw_T6"]
ann=lambda x: x*S/D*365/1e6
print("\n=== VMT TOLL RESULTS (annual, x4) ===")
print(f"T5 corridors 5.7c/mi : tolled VMT {t5v/b5-1:+.1%} vs base | revenue ${ann(t5m):.1f}M | no-diversion would be ${ann(b5*0.057):.1f}M")
print(f"T6 interstates 3.0c/mi: tolled VMT {t6v/b6-1:+.1%} vs base | revenue ${ann(t6m):.1f}M | no-diversion would be ${ann(b6*0.030):.1f}M")
if t5v>0 and t5m>0:
    eff5=t5m/(t5v)  # $ per tolled mile actually collected
    print(f"T5 effective $/tolled-mi {eff5:.3f}; rate to close R* net of diversion: {33.3e6/ann(t5v)/1e6*100:.1f} c/mi" if ann(t5v)>0 else "")
if t6v>0 and t6m>0:
    print(f"T6 rate to close R* net of diversion: {33.3e6/(t6v*S/D*365)*100:.1f} c/mi")
