import os
import requests
import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import uuid
import math
import pandas as pd

# ======================================================
# CONFIG
# ======================================================
DB_FILE = "chargepoint_md.db"
AFDC_CSV = "C:/Users/rtomal/Desktop/ChargePoint Data Collection/alt_fuel_stations (Jan 19 2026).csv"
CRAWL_INTERVAL = 600
BASE_URL = "https://mc.chargepoint.com/map-prod/v2?"

# Try wider radius first to confirm blobs exist, then tighten back
DISCOVERY_RADIUS_M = 1500
MATCH_MAX_DIST_M = 600

MAX_NEW_MATCHES_STARTUP = 120
MAX_NEW_MATCHES_PER_LOOP = 50

REQUEST_TIMEOUT = 30
POLITE_DELAY_S = 0.8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://driver.chargepoint.com/",
    "Origin": "https://driver.chargepoint.com",
    "Connection": "keep-alive"
}

# Requests session (keeps cookies)
SESSION = requests.Session()

# Debug payload dumping
DEBUG_DIR = "cp_debug_payloads"
os.makedirs(DEBUG_DIR, exist_ok=True)
DEBUG_SAVE_LIMIT_PER_RUN = 20  # avoid dumping thousands of files
_debug_saved = 0

# Use v2 table names to avoid collisions with old experiments
AFDC_TABLE = "afdc_station_v2"
STATION_TABLE = "charging_station_v2"
CROSSWALK_TABLE = "afdc_cp_crosswalk_v2"
SESSION_TABLE = "charging_session_v2"
STATUS_TABLE = "afdc_cp_crosswalk_status_v2"

# ======================================================
# TIME HELPERS (timezone-aware UTC)
# ======================================================
def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def add_minutes_iso(minutes: int):
    return (datetime.now(timezone.utc) + timedelta(minutes=int(minutes))).isoformat()

# ======================================================
# GEO HELPERS
# ======================================================
def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def bbox_from_point(lat, lon, radius_m):
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon, lat - dlat, lon - dlon  # ne_lat, ne_lon, sw_lat, sw_lon

# ======================================================
# DB HELPERS
# ======================================================
def table_cols(cur, table_name):
    cur.execute(f"PRAGMA table_info({table_name})")
    return [r[1] for r in cur.fetchall()]

def ensure_column(cur, table_name, col_name, col_type):
    cols = set(table_cols(cur, table_name))
    if col_name not in cols:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")

# ======================================================
# DATABASE INIT + MIGRATION
# ======================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {AFDC_TABLE} (
        afdc_station_id TEXT PRIMARY KEY,
        fuel_type_code TEXT,
        ev_network TEXT,
        status_code TEXT,
        station_name TEXT,
        street_address TEXT,
        city TEXT,
        state TEXT,
        zip TEXT,
        latitude REAL,
        longitude REAL,
        ev_l2_num INTEGER,
        ev_dc_fast_count INTEGER,
        ev_connector_types TEXT,
        updated_at TEXT
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {STATION_TABLE} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cp_key TEXT UNIQUE,
        status BOOLEAN,
        address TEXT,
        num_ports INTEGER,
        latitude REAL,
        longitude REAL,
        url TEXT
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {CROSSWALK_TABLE} (
        afdc_station_id TEXT PRIMARY KEY,
        station_id INTEGER,
        match_distance_m REAL,
        match_method TEXT,
        last_verified_utc TEXT,
        FOREIGN KEY(station_id) REFERENCES {STATION_TABLE}(id)
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {SESSION_TABLE} (
        uid TEXT PRIMARY KEY,
        station_id INTEGER,
        accessed_time_utc TEXT,
        in_use_ports INTEGER,
        available_ports INTEGER,
        other_ports INTEGER,
        FOREIGN KEY(station_id) REFERENCES {STATION_TABLE}(id)
    )
    """)

    cur.execute(f"""
    CREATE TABLE IF NOT EXISTS {STATUS_TABLE} (
        afdc_station_id TEXT PRIMARY KEY,
        last_attempt_utc TEXT,
        attempts INTEGER DEFAULT 0,
        last_result TEXT,
        last_error TEXT,
        next_retry_utc TEXT
    )
    """)

    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_v2_sessions_station_time ON {SESSION_TABLE}(station_id, accessed_time_utc)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_v2_station_latlon ON {STATION_TABLE}(latitude, longitude)")
    cur.execute(f"CREATE INDEX IF NOT EXISTS idx_v2_status_next_retry ON {STATUS_TABLE}(next_retry_utc)")

    for (col, typ) in [
        ("fuel_type_code", "TEXT"),
        ("ev_network", "TEXT"),
        ("status_code", "TEXT"),
        ("station_name", "TEXT"),
        ("street_address", "TEXT"),
        ("city", "TEXT"),
        ("state", "TEXT"),
        ("zip", "TEXT"),
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("ev_l2_num", "INTEGER"),
        ("ev_dc_fast_count", "INTEGER"),
        ("ev_connector_types", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        ensure_column(cur, AFDC_TABLE, col, typ)

    conn.commit()
    conn.close()

# ======================================================
# WARMUP (cookies)
# ======================================================
def warm_up_session():
    try:
        SESSION.get("https://driver.chargepoint.com/", headers=HEADERS, timeout=REQUEST_TIMEOUT)
        time.sleep(1.0)
    except Exception:
        pass

# ======================================================
# CHARGEPOINT QUERY
# ======================================================
def build_query(ne_lat, ne_lon, sw_lat, sw_lon):
    payload = {
        "map_data": {
            "screen_width": 800,
            "screen_height": 600,
            "ne_lat": ne_lat,
            "ne_lon": ne_lon,
            "sw_lat": sw_lat,
            "sw_lon": sw_lon,
            "filter": {
                "price_free": False,
                "status_available": False,
                "dc_fast_charging": False,
                "disabled_parking": False,
                "van_accessible": False,
                "network_chargepoint": False,
                "network_mercedes": False,
                "connector_l1": False,
                "connector_l2": False,
                "connector_l2_nema_1450": False,
                "connector_l2_tesla": False,
                "connector_chademo": False,
                "connector_combo": False,
                "connector_tesla": False
            },
            "bound_output": True
        }
    }
    return BASE_URL + quote(json.dumps(payload))

def _maybe_dump_payload(tag, payload_json):
    global _debug_saved
    if _debug_saved >= DEBUG_SAVE_LIMIT_PER_RUN:
        return
    fname = os.path.join(DEBUG_DIR, f"{tag}_{int(time.time())}_{_debug_saved}.json")
    try:
        with open(fname, "w") as f:
            json.dump(payload_json, f)
        _debug_saved += 1
    except Exception:
        pass

def fetch_blobs_bbox(ne_lat, ne_lon, sw_lat, sw_lon):
    """
    Defensive fetch: never KeyError on 'blobs'.
    If blobs are missing/empty, dumps payload for debugging (limited).
    """
    url = build_query(ne_lat, ne_lon, sw_lat, sw_lon)
    r = SESSION.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)

    if r.status_code != 200:
        raise requests.HTTPError(f"HTTP {r.status_code}: {r.text[:200]}")

    try:
        j = r.json()
    except Exception:
        raise ValueError(f"Non-JSON response: {r.text[:200]}")

    map_data = j.get("map_data")
    if not isinstance(map_data, dict):
        _maybe_dump_payload("missing_map_data", j)
        return []

    blobs = map_data.get("blobs")
    if blobs is None or not isinstance(blobs, list) or len(blobs) == 0:
        _maybe_dump_payload("no_blobs", j)
        return []

    return blobs

# ======================================================
# AFDC LOADING
# ======================================================
def load_afdc_chargepoint_elec(csv_path):
    df = pd.read_csv(csv_path)

    required = ["Fuel Type Code", "EV Network", "Status Code", "Latitude", "Longitude", "ID"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required AFDC columns: {missing}")

    df["Fuel Type Code"] = df["Fuel Type Code"].astype(str)
    df["EV Network"] = df["EV Network"].astype(str)
    df["Status Code"] = df["Status Code"].astype(str)

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df.dropna(subset=["Latitude", "Longitude"]).copy()

    df = df[
        df["Fuel Type Code"].str.upper().eq("ELEC") &
        df["EV Network"].str.contains("ChargePoint", case=False, na=False) &
        df["Status Code"].str.upper().eq("E")
    ].copy()

    out = pd.DataFrame({
        "afdc_station_id": df["ID"].astype(str),
        "fuel_type_code": df["Fuel Type Code"],
        "ev_network": df["EV Network"],
        "status_code": df["Status Code"],
        "station_name": df["Station Name"] if "Station Name" in df.columns else "",
        "street_address": df["Street Address"] if "Street Address" in df.columns else "",
        "city": df["City"] if "City" in df.columns else "",
        "state": df["State"] if "State" in df.columns else "",
        "zip": df["ZIP"].astype(str) if "ZIP" in df.columns else "",
        "latitude": df["Latitude"],
        "longitude": df["Longitude"],
        "ev_l2_num": pd.to_numeric(df["EV Level2 EVSE Num"], errors="coerce").fillna(0).astype(int)
            if "EV Level2 EVSE Num" in df.columns else 0,
        "ev_dc_fast_count": pd.to_numeric(df["EV DC Fast Count"], errors="coerce").fillna(0).astype(int)
            if "EV DC Fast Count" in df.columns else 0,
        "ev_connector_types": df["EV Connector Types"] if "EV Connector Types" in df.columns else "",
        "updated_at": df["Updated At"] if "Updated At" in df.columns else ""
    })
    return out

def upsert_afdc(df_afdc):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    for _, r in df_afdc.iterrows():
        cur.execute(f"""
        INSERT OR REPLACE INTO {AFDC_TABLE} (
            afdc_station_id, fuel_type_code, ev_network, status_code,
            station_name, street_address, city, state, zip,
            latitude, longitude, ev_l2_num, ev_dc_fast_count, ev_connector_types, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(r["afdc_station_id"]),
            str(r.get("fuel_type_code", "")),
            str(r.get("ev_network", "")),
            str(r.get("status_code", "")),
            str(r.get("station_name", "")),
            str(r.get("street_address", "")),
            str(r.get("city", "")),
            str(r.get("state", "")),
            str(r.get("zip", "")),
            float(r["latitude"]),
            float(r["longitude"]),
            int(r.get("ev_l2_num", 0) or 0),
            int(r.get("ev_dc_fast_count", 0) or 0),
            str(r.get("ev_connector_types", "")),
            str(r.get("updated_at", "")),
        ))
    conn.commit()
    conn.close()

# ======================================================
# CP STATION + CROSSWALK
# ======================================================
def blob_cp_key(blob):
    for k in ["station_id", "place_id", "id", "device_id", "loc_id"]:
        if k in blob and blob[k] is not None:
            return f"{k}:{blob[k]}"
    return f"latlon:{float(blob['lat']):.6f},{float(blob['lon']):.6f}"

def upsert_station_from_blob(cur, blob):
    cp_key = blob_cp_key(blob)
    lat = float(blob["lat"])
    lon = float(blob["lon"])

    pc = blob.get("port_count", {}) or {}
    in_use = int(pc.get("in_use", 0) or 0)
    available = int(pc.get("available", 0) or 0)
    other = int(pc.get("other", 0) or 0)
    num_ports = in_use + available + other

    cur.execute(f"SELECT id FROM {STATION_TABLE} WHERE cp_key=?", (cp_key,))
    row = cur.fetchone()
    if row:
        sid = row[0]
        cur.execute(f"UPDATE {STATION_TABLE} SET num_ports=?, latitude=?, longitude=? WHERE id=?",
                    (num_ports, lat, lon, sid))
        return sid

    cur.execute(f"""
        INSERT INTO {STATION_TABLE} (cp_key, status, address, num_ports, latitude, longitude, url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (cp_key, True, None, num_ports, lat, lon, "https://driver.chargepoint.com"))
    return cur.lastrowid

def discover_one_crosswalk(afdc_id, lat, lon):
    ne_lat, ne_lon, sw_lat, sw_lon = bbox_from_point(lat, lon, DISCOVERY_RADIUS_M)
    blobs = fetch_blobs_bbox(ne_lat, ne_lon, sw_lat, sw_lon)
    if not blobs:
        return None

    best, best_d = None, float("inf")
    for b in blobs:
        d = haversine_m(lat, lon, float(b["lat"]), float(b["lon"]))
        if d < best_d:
            best_d, best = d, b

    if best is None or best_d > MATCH_MAX_DIST_M:
        return None

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    sid = upsert_station_from_blob(cur, best)

    cur.execute(f"""
        INSERT OR REPLACE INTO {CROSSWALK_TABLE}
        (afdc_station_id, station_id, match_distance_m, match_method, last_verified_utc)
        VALUES (?, ?, ?, ?, ?)
    """, (str(afdc_id), int(sid), float(best_d), "nearest_blob", utc_now_iso()))

    conn.commit()
    conn.close()
    return sid

def record_status(afdc_id, attempts, result, err=None, retry_minutes=60):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(f"""
        INSERT OR REPLACE INTO {STATUS_TABLE}
        (afdc_station_id, last_attempt_utc, attempts, last_result, last_error, next_retry_utc)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(afdc_id),
        utc_now_iso(),
        int(attempts),
        str(result),
        (str(err)[:500] if err else None),
        add_minutes_iso(retry_minutes)
    ))
    conn.commit()
    conn.close()

def ensure_crosswalk(limit_new, verbose=False):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    now = utc_now_iso()

    cur.execute(f"""
        SELECT a.afdc_station_id, a.latitude, a.longitude,
               st.attempts, st.next_retry_utc
        FROM {AFDC_TABLE} a
        LEFT JOIN {CROSSWALK_TABLE} x ON a.afdc_station_id = x.afdc_station_id
        LEFT JOIN {STATUS_TABLE} st ON a.afdc_station_id = st.afdc_station_id
        WHERE x.afdc_station_id IS NULL
          AND (st.next_retry_utc IS NULL OR st.next_retry_utc <= ?)
        LIMIT ?
    """, (now, int(limit_new)))
    targets = cur.fetchall()
    conn.close()

    stats = {"matched": 0, "no_blobs": 0, "too_far": 0, "http_error": 0, "other": 0}

    for afdc_id, lat, lon, attempts, _ in targets:
        attempts = int(attempts or 0) + 1
        try:
            sid = discover_one_crosswalk(str(afdc_id), float(lat), float(lon))
            if sid is not None:
                stats["matched"] += 1
                record_status(afdc_id, attempts, "matched", err=None, retry_minutes=7 * 24 * 60)
            else:
                stats["no_blobs"] += 1
                delay = min(24 * 60, 30 * (2 ** min(attempts, 5)))
                record_status(afdc_id, attempts, "no_blobs", err=None, retry_minutes=delay)

            time.sleep(POLITE_DELAY_S)

        except requests.HTTPError as e:
            stats["http_error"] += 1
            delay = min(24 * 60, 10 * (2 ** min(attempts, 6)))
            record_status(afdc_id, attempts, "http_error", err=e, retry_minutes=delay)
            if verbose:
                print("Crosswalk http_error:", afdc_id, e)

        except Exception as e:
            stats["other"] += 1
            delay = min(24 * 60, 30 * (2 ** min(attempts, 5)))
            record_status(afdc_id, attempts, "other", err=e, retry_minutes=delay)
            if verbose:
                print("Crosswalk other_error:", afdc_id, e)

    if sum(stats.values()) > 0:
        print(f"[{datetime.now(timezone.utc)}] Crosswalk: {stats}")

# ======================================================
# UTILIZATION
# ======================================================
def scrape_sessions_for_matched(verbose=False):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(f"""
        SELECT x.afdc_station_id, s.id, s.latitude, s.longitude
        FROM {CROSSWALK_TABLE} x
        JOIN {STATION_TABLE} s ON x.station_id = s.id
    """)
    matched = cur.fetchall()

    now = utc_now_iso()
    saved = 0
    misses = 0

    for afdc_id, station_id, lat, lon in matched:
        try:
            ne_lat, ne_lon, sw_lat, sw_lon = bbox_from_point(float(lat), float(lon), DISCOVERY_RADIUS_M)
            blobs = fetch_blobs_bbox(ne_lat, ne_lon, sw_lat, sw_lon)
            if not blobs:
                misses += 1
                continue

            best, best_d = None, float("inf")
            for b in blobs:
                d = haversine_m(float(lat), float(lon), float(b["lat"]), float(b["lon"]))
                if d < best_d:
                    best_d, best = d, b

            if best is None or best_d > MATCH_MAX_DIST_M:
                misses += 1
                continue

            pc = best.get("port_count", {}) or {}
            in_use = int(pc.get("in_use", 0) or 0)
            available = int(pc.get("available", 0) or 0)
            other = int(pc.get("other", 0) or 0)

            cur.execute(f"""
                INSERT INTO {SESSION_TABLE}
                (uid, station_id, accessed_time_utc, in_use_ports, available_ports, other_ports)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), int(station_id), now, in_use, available, other))
            saved += 1

        except Exception as e:
            if verbose:
                print("Scrape error:", afdc_id, e)

    conn.commit()
    conn.close()

    print(f"[{datetime.now(timezone.utc)}] Utilization: saved={saved}, misses={misses}, matched_stations={len(matched)}")
    return saved

# ======================================================
# MAIN
# ======================================================
def run():
    print("Initializing DB...")
    init_db()

    print("Warming up session...")
    warm_up_session()

    print("Loading AFDC (ChargePoint + ELEC + existing)...")
    df_afdc = load_afdc_chargepoint_elec(AFDC_CSV)
    print(f"AFDC filtered stations: {len(df_afdc)}")
    upsert_afdc(df_afdc)

    print("Building crosswalk (startup)...")
    ensure_crosswalk(limit_new=MAX_NEW_MATCHES_STARTUP, verbose=False)

    print("Starting utilization crawler...")
    while True:
        try:
            ensure_crosswalk(limit_new=MAX_NEW_MATCHES_PER_LOOP, verbose=False)
            scrape_sessions_for_matched(verbose=False)
        except Exception as e:
            print("Loop error:", e)

        print(f"Sleeping for {CRAWL_INTERVAL} seconds...\n")
        time.sleep(CRAWL_INTERVAL)

if __name__ == "__main__":
    run()
