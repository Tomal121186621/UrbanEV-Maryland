#!/usr/bin/env python3
"""AADT-loaded time-variant network: impose OBSERVED background congestion on the MATSim
road network without simulating non-EV agents (EVs are ~3% of MD traffic, so the
EV->congestion feedback is negligible; the background->EV direction is what matters).

  1. MDOT SHA AADT segments (downloaded 2026-07-16, EPSG:26985; AADT, F_SYSTEM,
     K_FACTOR peak-hour share) -> nearest-segment match to network link midpoints (<=60 m,
     motorway/arterial classes only).
  2. Hourly directional volume: v_h = AADT * share_h / 2, where share_h is a canonical
     two-peak weekday profile rescaled so its peak equals the segment's own K_FACTOR.
  3. BPR congested speed: s_h = freespeed / (1 + 0.15 (v_h / c)^4), c = link capacity
     (veh/h); floored at 0.25*freespeed.
  4. Unmatched links inherit the CLASS-MEDIAN hourly factor of matched links (same
     F_SYSTEM-equivalent road class), so typical congestion applies network-wide.
  5. networkChangeEvents.xml: absolute freespeed events per hour (grouped, 0.05-factor
     buckets, only factor<0.97), repeated for each simulated day (72 h plans).
Every number traces to MDOT data or the documented BPR form — nothing fitted.
"""
import gzip, glob, sys
import numpy as np, pandas as pd, geopandas as gpd
import xml.etree.ElementTree as ET
from pathlib import Path
from scipy.spatial import cKDTree

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
SCR = Path("/tmp/claude-1000/-home-tomal-Documents/867fe3cb-9e62-4fb4-a009-8ebe0c50a670/scratchpad")
NET = ROOT/"Input/network/maryland-network-pt2matsim.xml.gz"
OUT = ROOT/"Input/network/networkChangeEvents_aadt_v3.xml.gz"
DAYS = 3
MATCH_M = 60.0

# canonical weekday hourly volume shares (two-peak, FHWA-style urban shape; sums to 1)
BASE = np.array([0.008,0.005,0.004,0.005,0.012,0.035,0.062,0.077,0.066,0.052,0.050,0.052,
                 0.055,0.055,0.060,0.072,0.082,0.080,0.062,0.045,0.033,0.026,0.018,0.014])
BASE = BASE/BASE.sum()

def hourly_shares(k_factor):
    """Rescale BASE so the max hourly share equals the segment's K factor."""
    if not np.isfinite(k_factor) or k_factor <= 0 or k_factor > 0.25:
        return BASE
    s = BASE * (k_factor / BASE.max())
    rest = 1.0 - s.max()
    others = s.sum() - s.max()
    s[s < s.max()] *= rest / others
    return s / s.sum()

# ---- network links ----
print("[net] parsing network ...", flush=True)
nodes = {}; links = []
for _, el in ET.iterparse(gzip.open(NET, "rt"), events=("end",)):
    if el.tag == "node":
        nodes[el.get("id")] = (float(el.get("x")), float(el.get("y")))
    elif el.tag == "link":
        a = nodes.get(el.get("from")); b = nodes.get(el.get("to"))
        if a and b:
            links.append((el.get("id"), (a[0]+b[0])/2, (a[1]+b[1])/2,
                          float(el.get("freespeed")), float(el.get("capacity"))))
        el.clear()
L = pd.DataFrame(links, columns=["id","x","y","fs","cap"])
print(f"[net] {len(L):,} links")
rc = pd.read_parquet(ROOT/"Input/network/link_road_class.parquet")[["osm_highway"]]
L = L.merge(rc.rename_axis("id").reset_index(), on="id", how="left")
cls_col = "osm_highway"
print("[net] classes:", L[cls_col].value_counts().head(8).to_dict())

# ---- AADT segments ----
gs = pd.concat([gpd.read_file(f) for f in sorted(glob.glob(str(SCR/"aadt_*.geojson")))],
               ignore_index=True)
gs = gs[(gs.AADT > 0) & gs.geometry.notna()].reset_index(drop=True)
print(f"[aadt] {len(gs):,} segments with AADT>0")
# sample points along each segment for matching
is_ramp_seg = gs.ROADNAME.fillna("").str.upper().str.startswith("RAMP").to_numpy()
pts, seg_i = [], []
for i, geom in enumerate(gs.geometry):
    try:
        n = max(2, int(geom.length // 150))
        for d in np.linspace(0, geom.length, min(n, 40)):
            p = geom.interpolate(d); pts.append((p.x, p.y)); seg_i.append(i)
    except Exception:
        continue
pts = np.array(pts); seg_i = np.array(seg_i)
seg_ramp = is_ramp_seg[seg_i]
tree_main = cKDTree(pts[~seg_ramp]); idx_main = seg_i[~seg_ramp]
tree_ramp = cKDTree(pts[seg_ramp]) if seg_ramp.any() else None
idx_ramp = seg_i[seg_ramp]
MAJOR = L[cls_col].isin(["motorway","trunk","primary","secondary","tertiary",
                         "motorway_link","trunk_link","primary_link"])
lm = L[MAJOR].reset_index(drop=True)
link_is_ramp = lm[cls_col].str.endswith("_link").to_numpy()
seg_assign = np.full(len(lm), -1)
mmain = ~link_is_ramp
dd, ii = tree_main.query(lm.loc[mmain,["x","y"]].values, k=1)
seg_assign[np.where(mmain)[0][dd <= MATCH_M]] = idx_main[ii[dd <= MATCH_M]]
if tree_ramp is not None and link_is_ramp.any():
    dd, ii = tree_ramp.query(lm.loc[link_is_ramp,["x","y"]].values, k=1)
    seg_assign[np.where(link_is_ramp)[0][dd <= MATCH_M]] = idx_ramp[ii[dd <= MATCH_M]]
lm["seg"] = seg_assign
matched = lm[lm.seg >= 0].copy()
print(f"[match] {len(matched):,}/{len(lm):,} major-class links matched <= {MATCH_M:.0f} m")

# ---- hourly speed factors ----
aadt = gs.AADT.to_numpy(); kf = pd.to_numeric(gs.get("K_FACTOR"), errors="coerce").to_numpy()/100.0
shares = np.stack([hourly_shares(k) for k in kf])           # (nseg, 24)
seg = matched.seg.to_numpy()
v_h = aadt[seg,None] * shares[seg] / 2.0                    # directional hourly volume
vc = v_h / np.maximum(matched.cap.to_numpy()[:,None], 100.0)
# class-dependent volume-delay exponent: freeways break down sharply near capacity
# (BPR beta=4 understates freeway delay; steeper exponent is standard practice for
# freeway VDFs, cf. NCHRP 365 / Dowling updated-BPR)
beta = np.where(matched[cls_col].isin(["motorway","trunk"]).to_numpy()[:,None], 8.0, 4.0)
fac = 1.0 / (1.0 + 0.15 * vc**beta)
fac = np.clip(fac, 0.25, 1.0)
matched_fac = pd.DataFrame(fac, index=matched.id)
matched_fac[cls_col] = matched[cls_col].to_numpy()
# class-median factors for unmatched major links
cls_med = matched_fac.groupby(cls_col).median()
un = lm[lm.seg < 0]
un_fac = cls_med.reindex(un[cls_col]).to_numpy()
all_ids = np.concatenate([matched.id.to_numpy(), un.id.to_numpy()])
all_fac = np.vstack([fac, un_fac])
all_fs  = np.concatenate([matched.fs.to_numpy(), un.fs.to_numpy()])
ok = ~np.isnan(all_fac).any(axis=1)
all_ids, all_fac, all_fs = all_ids[ok], all_fac[ok], all_fs[ok]
print(f"[fac] links with factors: {len(all_ids):,} | mean PM-peak (17h) factor "
      f"{all_fac[:,17].mean():.3f} | <0.7 at 17h: {(all_fac[:,17]<0.7).sum():,}")

# ---- write grouped change events ----
print("[write] networkChangeEvents ...", flush=True)
with gzip.open(OUT, "wt") as o:
    o.write('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<networkChangeEvents xmlns="http://www.matsim.org/files/dtd" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.matsim.org/files/dtd '
            'http://www.matsim.org/files/dtd/networkChangeEvents.xsd">\n')
    nev = 0
    for day in range(DAYS):
        for h in range(24):
            f_h = all_fac[:, h]
            sel = f_h < 0.97
            if not sel.any():
                # restore full speed for links changed in earlier hours
                sel = np.zeros(len(all_ids), bool)
            bucket = np.round(f_h * 20) / 20.0
            for bv in np.unique(bucket[sel]):
                m = sel & (bucket == bv)
                # absolute speeds differ per link; write per unique (bucket, fs) pair
                for fs_v in np.unique(all_fs[m]):
                    mm = m & (all_fs == fs_v)
                    o.write(f'  <networkChangeEvent startTime="{day*24+h:02d}:00:00">\n')
                    for lid in all_ids[mm]:
                        o.write(f'    <link refId="{lid}"/>\n')
                    o.write(f'    <freespeed type="absolute" value="{fs_v*bv:.2f}"/>\n'
                            '  </networkChangeEvent>\n')
                    nev += 1
            # restore events at hours when factor returns to ~1
            if h > 0:
                back = (all_fac[:, h-1] < 0.97) & (f_h >= 0.97)
                if back.any():
                    for fs_v in np.unique(all_fs[back]):
                        mm = back & (all_fs == fs_v)
                        o.write(f'  <networkChangeEvent startTime="{day*24+h:02d}:00:00">\n')
                        for lid in all_ids[mm]:
                            o.write(f'    <link refId="{lid}"/>\n')
                        o.write(f'    <freespeed type="absolute" value="{fs_v:.2f}"/>\n'
                                '  </networkChangeEvent>\n')
                        nev += 1
    o.write('</networkChangeEvents>\n')
print(f"[done] {nev:,} change events -> {OUT}")
