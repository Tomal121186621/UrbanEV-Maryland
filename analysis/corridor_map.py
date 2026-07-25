#!/usr/bin/env python3
"""
corridor_map.py — label each Maryland network link with its named highway corridor
(I-95, I-270, Capital Beltway I-495, Baltimore Beltway I-695, I-70, I-83, US-50, US-40,
US-301 ...) by spatially matching motorway/trunk network links to OSM reference lines.
Saves link_corridor.parquet (link -> corridor) and reports EV VMT by corridor.
"""
import sys, gzip
from pathlib import Path
import numpy as np, pandas as pd, xml.etree.ElementTree as ET
import geopandas as gpd
from shapely.geometry import LineString
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
PBF = REPO / "pipeline/data/osm/maryland-latest.osm.pbf"
NET = REPO / "Input/network/maryland-network-pt2matsim.xml.gz"
RC = REPO / "Input/network/link_road_class.parquet"
B = ROOT / "scenarios/maryland/output/runs_2026/baseline"
OUT = B / "route_analysis"

# ref -> corridor label (grouped)
def corridor(ref):
    r = str(ref).split(";")[0].strip()
    named = {"I 95": "I-95", "I 270": "I-270", "I 495": "I-495 (Capital Beltway)",
             "I 695": "I-695 (Baltimore Beltway)", "I 70": "I-70", "I 83": "I-83",
             "I 97": "I-97", "I 895": "I-895", "US 50": "US-50", "US 40": "US-40",
             "US 301": "US-301", "US 1": "US-1", "US 29": "US-29"}
    return named.get(r, None)


def main():
    # OSM ref lines
    g = gpd.read_file(PBF, layer="lines", engine="pyogrio", columns=["highway", "other_tags"])
    g = g[g.highway.isin(["motorway", "trunk", "motorway_link", "trunk_link"])].copy()
    g["ref"] = g.other_tags.str.extract(r'"ref"=>"([^"]+)"')[0]
    g["corr"] = g.ref.map(corridor)
    g = g[g["corr"].notna()].set_crs("EPSG:4326").to_crs("EPSG:26985")
    corr = g.dissolve("corr")

    # network geometry (motorway/trunk-ish links only, via road_class interstate/arterial)
    rc = pd.read_parquet(RC)
    nodes = {}; rows = []
    for _, el in ET.iterparse(gzip.open(NET, "rt"), events=("end",)):
        if el.tag == "node":
            nodes[el.get("id")] = (float(el.get("x")), float(el.get("y")))
        elif el.tag == "link":
            f, t = nodes.get(el.get("from")), nodes.get(el.get("to"))
            if f and t:
                rows.append((el.get("id"), (f[0] + t[0]) / 2, (f[1] + t[1]) / 2))
            el.clear()
    net = pd.DataFrame(rows, columns=["link", "mx", "my"]).set_index("link")
    net["road_class"] = rc.road_class.reindex(net.index)
    cand = net[net.road_class.isin(["interstate", "arterial"])].copy()
    gn = gpd.GeoDataFrame(cand, geometry=gpd.points_from_xy(cand.mx, cand.my), crs="EPSG:26985")

    # nearest corridor within 120 m
    j = gpd.sjoin_nearest(gn, corr.reset_index()[["corr", "geometry"]], max_distance=120, how="left")
    j = j[~j.index.duplicated()]
    link_corr = j["corr"].dropna()
    link_corr.rename("corridor").to_frame().to_parquet(OUT / "link_corridor.parquet")

    # EV VMT by corridor (from saved link VMT)
    lv = pd.read_parquet(OUT / "link_vmt.parquet")
    m = lv.join(link_corr.rename("corridor")).dropna(subset=["corridor"])
    byc = m.groupby("corridor").vmt.sum().sort_values(ascending=False)
    print("EV VMT by corridor (mi/day):"); print(byc.round(0).to_string())
    print(f"\nlinks labelled: {len(link_corr):,}; corridors: {byc.index.nunique()}")
    fig, ax = pf.newfig(6, 4.4)
    ax.barh(byc.index[::-1], byc.values[::-1] / 1000, color=pf.BLUE, edgecolor="k", lw=0.3)
    ax.set(xlabel="EV VMT (thousand mi/day)", title="EV vehicle-miles by highway corridor")
    pf.save(fig, OUT, "vmt_by_corridor")
    byc.rename("vmt_mi_day").to_csv(REPO / "paper/tables/vmt_by_corridor.csv")


if __name__ == "__main__":
    main()
