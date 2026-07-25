#!/usr/bin/env python3
"""
05_osm_pois.py — extract categorized OpenStreetMap POIs for activity geolocation.

Reads the Maryland OSM extract (data/osm/maryland-latest.osm.pbf) and classifies
point + building/landuse features into RTS destination-activity categories (d_activity
codes 1..18). Each POI is tagged with the activity code(s) it can serve; the plan
builder later places a trip's destination at a type-matched POI at ~the generated trip
distance from the previous location. Output: data/osm/pois.parquet (x, y in EPSG:26985,
act). Home (1) is not extracted here — home uses the agent's own home coordinate.
"""
from __future__ import annotations
import sys, re
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
PBF = ROOT / "pipeline/data/osm/maryland-latest.osm.pbf"
OUT = ROOT / "pipeline/data/osm/pois.parquet"
CRS_M = "EPSG:26985"          # NAD83 / Maryland (metres) — matches tract_centroids

# RTS d_activity code -> {osm_key: set_of_values or "*"} that can serve that activity.
ACT = {
    2:  {"office": "*", "amenity": {"bank", "post_office", "townhall", "courthouse"},
         "shop": {"mall", "department_store", "supermarket"}},                       # Work
    4:  {"amenity": {"school", "university", "college", "kindergarten", "library"}},  # School
    5:  {"shop": "*"},                                                               # Shopping
    6:  {"amenity": {"fast_food", "cafe", "ice_cream", "food_court"}},               # Quick meal
    7:  {"amenity": {"restaurant"}},                                                 # Meal
    8:  {"amenity": {"fuel", "charging_station"}},                                   # Gas/fuel
    9:  {"amenity": {"hospital", "clinic", "doctors", "dentist", "pharmacy", "veterinary"},
         "healthcare": "*"},                                                         # Health care
    10: {"amenity": {"bank", "post_office", "atm", "fuel", "car_wash"},
         "shop": {"laundry", "hairdresser", "car_repair", "dry_cleaning"}},          # Errand
    11: {"amenity": {"bar", "pub", "nightclub", "community_centre", "social_facility"}},  # Socialize
    12: {"amenity": {"place_of_worship", "townhall", "library", "community_centre"}},     # Civic/Relig.
    13: {"leisure": {"fitness_centre", "sports_centre", "stadium", "pitch", "track", "gym"},
         "amenity": {"gym"}},                                                        # Exercise
    14: {"leisure": {"park", "garden", "nature_reserve", "playground", "recreation_ground"},
         "tourism": {"attraction", "viewpoint", "picnic_site"}},                     # Recreation
    15: {"amenity": {"cinema", "theatre", "arts_centre", "casino", "nightclub"},
         "tourism": {"museum", "gallery", "zoo", "theme_park", "aquarium"}},         # Entertainment
}
KEYS = sorted({k for m in ACT.values() for k in m})      # osm keys we need from other_tags


def parse_tags(series):
    """Extract the KEYS we care about from the HSTORE `other_tags` strings -> DataFrame."""
    pat = {k: re.compile(rf'"{k}"=>"([^"]*)"') for k in KEYS}
    out = {k: [] for k in KEYS}
    for s in series.fillna(""):
        for k, rgx in pat.items():
            m = rgx.search(s)
            out[k].append(m.group(1) if m else None)
    return pd.DataFrame(out)


def categorize(tags: pd.DataFrame) -> list:
    """For each row, list of activity codes it can serve."""
    codes = [[] for _ in range(len(tags))]
    for act, spec in ACT.items():
        mask = np.zeros(len(tags), bool)
        for key, vals in spec.items():
            col = tags[key]
            mask |= col.notna() if vals == "*" else col.isin(vals)
        for i in np.nonzero(mask)[0]:
            codes[i].append(act)
    return codes


def load_layer(layer):
    print(f"[read] {layer} ...", flush=True)
    # GDAL's OSM driver PROMOTES amenity/shop/leisure/tourism/office etc. to dedicated
    # columns on the multipolygons layer (they are NOT in other_tags there); the points
    # layer keeps them in other_tags. Request both and OR them together.
    import pyogrio
    avail = set(pyogrio.read_info(PBF, layer=layer)["fields"])
    prom = [k for k in KEYS if k in avail]
    g = gpd.read_file(PBF, layer=layer, engine="pyogrio",
                      columns=["osm_id", "other_tags"] + prom)
    tags = parse_tags(g.other_tags)
    for k in prom:                                  # promoted column wins where present
        tags[k] = g[k].where(g[k].notna(), tags[k].values)
    g["_codes"] = categorize(tags)
    g = g[g._codes.map(len) > 0].reset_index(drop=True)
    if layer == "multipolygons":
        g["geometry"] = g.geometry.representative_point()      # polygon -> interior point
    g = g.set_crs("EPSG:4326").to_crs(CRS_M)
    return g[["geometry", "_codes"]]


def main():
    parts = [load_layer("points"), load_layer("multipolygons")]
    g = pd.concat(parts, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=CRS_M)
    g = g[g.geometry.notna() & (g.geometry.geom_type == "Point")]
    rows = []
    for geom, codes in zip(g.geometry.values, g._codes.values):
        for c in codes:
            rows.append((geom.x, geom.y, c))
    poi = pd.DataFrame(rows, columns=["x", "y", "act"])
    poi.to_parquet(OUT, index=False)
    print(f"\n[save] {len(poi):,} (POI, activity) rows -> {OUT}")
    print("per-activity POI counts:")
    print(poi.act.value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
