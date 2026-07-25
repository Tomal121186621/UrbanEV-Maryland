#!/usr/bin/env python3
"""
calibration_loss.py — calibration loss for the Phase 5 BO loop.

Given a single MATSim iteration directory (typically the last iter of a calib
run), compute a scalar loss against held-out observed data:

    L = w_kl * KL(sim_session_kWh ‖ evwatts_session_kWh)
      + w_mape * MAPE(sim_24hr_occupancy, chargepoint_24hr_occupancy)
      + w_share * | sim_DCFC_share - evwatts_DCFC_share |

All comparisons respect the train/dev/test hold-out manifests in splits/.
By default reads only the TRAIN splits. Dev loss is logged as a side metric.
TEST is locked out unless --unlock-test is given (touch-once policy).

Sim sources (per iteration directory):
    {iter}.chargingStats.csv              -> per-session rows
    {iter}.charger_occupancy_absolute.xy  -> per-station 24-hr occupancy

Observed sources:
    EVWatts MD-metro session table        -> session-energy KDE
    chargepoint_md.db charging_session_v2 -> per-station 24-hr occupancy

Hold-out manifests:
    splits/agents_{train,dev,test}.csv    (population hold-out)
    splits/stations_{train,dev,test}.csv  (station hold-out, ChargePoint IDs)

NOTE: this module is a skeleton — the empirical-data loaders are stubs that
document the expected schema and return synthetic data for unit-test runs.
Wire real loaders in Phase 5 once the EVWatts/ChargePoint preprocessing is done.

Usage (smoke):
    python analysis/calibration_loss.py \
        --iter-dir output/calib_10pct/ITERS/it.100 \
        --chargers-xml ../Input/chargers/chargers_10pct.xml \
        --splits splits/ \
        --weights kl=0.5,mape=0.4,share=0.1 \
        --out trial_001_loss.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Charger metadata (id -> type)
# ---------------------------------------------------------------------------
def load_charger_types(chargers_xml: Path) -> dict[str, str]:
    """Map charger id -> type from MATSim chargers.xml."""
    out: dict[str, str] = {}
    for _, el in ET.iterparse(chargers_xml, events=("end",)):
        if el.tag.endswith("charger"):
            out[el.get("id")] = el.get("type", "UNKNOWN")
            el.clear()
    return out


# ---------------------------------------------------------------------------
# Sim parsers
# ---------------------------------------------------------------------------
@dataclass
class Session:
    charger_id: str
    vehicle_id: str
    person_id: str          # derived from vehicle_id (shh_<n>_ev<k> -> shh_<n>_ev<k>)
    charger_type: str
    start_sec: float        # MATSim seconds (may exceed 86400 for multi-day)
    end_sec: float
    energy_kwh: float
    start_soc: float
    end_soc: float


def _vehicle_to_person(veh_id: str) -> str:
    """In this project vehicle id == person id (verified in subsample_population.py)."""
    return veh_id


def parse_charging_stats(stats_csv: Path,
                         charger_types: dict[str, str]) -> list[Session]:
    """Parse {iter}.chargingStats.csv → list[Session]. Semicolon-delimited."""
    sessions: list[Session] = []
    with stats_csv.open("r", encoding="utf-8") as f:
        header = next(f).rstrip("\n").split(";")
        idx = {name: i for i, name in enumerate(header)}
        for line in f:
            row = line.rstrip("\n").split(";")
            if len(row) < len(header):
                continue
            cid = row[idx["chargerId"]]
            vid = row[idx["vehicleId"]]
            try:
                sessions.append(Session(
                    charger_id=cid,
                    vehicle_id=vid,
                    person_id=_vehicle_to_person(vid),
                    charger_type=charger_types.get(cid, "UNKNOWN"),
                    start_sec=float(row[idx["startTime_matsim"]]),
                    end_sec=float(row[idx["endTime_matsim"]]),
                    energy_kwh=float(row[idx["transmittedEnergy_kWh"]]),
                    start_soc=float(row[idx["startSoc"]]),
                    end_soc=float(row[idx["endSoc"]]),
                ))
            except (KeyError, ValueError):
                continue
    return sessions


def parse_station_occupancy(xy_path: Path) -> dict[str, list[tuple[int, int]]]:
    """
    Parse {iter}.charger_occupancy_absolute.xy[.gz] →
        {charger_id: [(time_sec, plugged), ...]}

    File is tab-delimited with header: time, id, x, y, plugs, plugged.
    """
    opener = gzip.open if xy_path.suffix == ".gz" else open
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with opener(xy_path, "rt", encoding="utf-8", errors="replace") as f:
        header = next(f).rstrip("\n").split("\t")
        try:
            t_i = header.index("time")
            id_i = header.index("id")
            pl_i = header.index("plugged")
        except ValueError:
            raise RuntimeError(f"unexpected occupancy header: {header}")
        for line in f:
            row = line.rstrip("\n").split("\t")
            if len(row) <= max(t_i, id_i, pl_i):
                continue
            try:
                out[row[id_i]].append((int(float(row[t_i])), int(float(row[pl_i]))))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# Hold-out manifests
# ---------------------------------------------------------------------------
def load_id_set(csv_path: Path, key: str) -> set[str]:
    ids: set[str] = set()
    with csv_path.open("r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
        try:
            k = header.index(key)
        except ValueError:
            raise RuntimeError(f"column {key!r} not in {csv_path}")
        for line in f:
            row = line.rstrip("\n").split(",")
            if len(row) > k:
                ids.add(row[k])
    return ids


def load_cp_to_sim_crosswalk(csv_path: Path) -> dict[str, str]:
    """
    Returns {cp_station_id_str: sim_charger_id}. Reads
    splits/sim_to_cp_crosswalk.csv produced by crosswalk_sim_chargepoint.py.

    Multiple CP stations may map to the same sim id (collisions documented
    in the crosswalk manifest); we keep the last write — the filter only
    cares about set membership, not the specific CP→sim direction.
    """
    out: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split(",")
        cp_i = header.index("cp_station_id")
        sim_i = header.index("sim_charger_id")
        for line in f:
            row = line.rstrip("\n").split(",")
            if len(row) > max(cp_i, sim_i):
                out[row[cp_i]] = row[sim_i]
    return out


# ---------------------------------------------------------------------------
# Loss components
# ---------------------------------------------------------------------------
def kde_kl_divergence(sim_values: list[float],
                      obs_values: list[float],
                      bins: int = 30,
                      lo: float | None = None,
                      hi: float | None = None) -> float:
    """KL(sim ‖ obs) over a shared histogram support with Laplace smoothing."""
    if not sim_values or not obs_values:
        return float("inf")
    lo = lo if lo is not None else min(min(sim_values), min(obs_values))
    hi = hi if hi is not None else max(max(sim_values), max(obs_values))
    if hi <= lo:
        return 0.0
    width = (hi - lo) / bins
    sim_h = [0.0] * bins
    obs_h = [0.0] * bins
    for v in sim_values:
        i = min(bins - 1, max(0, int((v - lo) / width)))
        sim_h[i] += 1
    for v in obs_values:
        i = min(bins - 1, max(0, int((v - lo) / width)))
        obs_h[i] += 1
    eps = 1e-9
    sim_n = sum(sim_h) + bins * eps
    obs_n = sum(obs_h) + bins * eps
    kl = 0.0
    for s, o in zip(sim_h, obs_h):
        ps = (s + eps) / sim_n
        po = (o + eps) / obs_n
        kl += ps * math.log(ps / po)
    return kl


def mape(sim_series: list[float], obs_series: list[float]) -> float:
    """Mean absolute percentage error over aligned series. Skips obs==0 cells."""
    if len(sim_series) != len(obs_series) or not sim_series:
        return float("inf")
    errs = []
    for s, o in zip(sim_series, obs_series):
        if o == 0:
            continue
        errs.append(abs(s - o) / abs(o))
    return sum(errs) / len(errs) if errs else float("inf")


def to_24hr_profile(samples: list[tuple[int, int]],
                    bin_sec: int = 3600) -> list[float]:
    """Average plugged-count per hour-of-day (24 bins) over the run."""
    bins = 86400 // bin_sec
    sums = [0.0] * bins
    counts = [0] * bins
    for t, p in samples:
        h = (t % 86400) // bin_sec
        sums[h] += p
        counts[h] += 1
    return [(sums[i] / counts[i]) if counts[i] else 0.0 for i in range(bins)]


# ---------------------------------------------------------------------------
# Observed-data loader stubs (Phase 5 wiring)
# ---------------------------------------------------------------------------
def load_evwatts_session_kwh(_evwatts_dir: Path | None) -> list[float]:
    """
    TODO Phase 5: read EVWatts MD-metro session table and return per-session
    delivered energy in kWh. Filter to Maryland-county sessions only.

    For skeleton testing return empty -> KL term contributes inf, easy to spot.
    """
    return []


def load_evwatts_dcfc_share(_evwatts_dir: Path | None) -> float | None:
    """TODO Phase 5: fraction of EVWatts MD sessions on DCFC chargers."""
    return None


def load_chargepoint_24hr_profile(_cp_db: Path | None,
                                  _station_ids: set[str]) -> list[float]:
    """
    TODO Phase 5: aggregate average plugged count per hour-of-day across the
    given ChargePoint station_ids using charging_session_v2 in chargepoint_md.db
    (in_use_ports / available_ports / accessed_time_utc).
    """
    return []


# ---------------------------------------------------------------------------
# Top-level loss
# ---------------------------------------------------------------------------
@dataclass
class LossReport:
    loss: float
    components: dict[str, float]
    weights: dict[str, float]
    counts: dict[str, int]
    split: str  # "train" | "dev" | "test"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def compute_loss(iter_dir: Path,
                 chargers_xml: Path,
                 splits_dir: Path,
                 evwatts_dir: Path | None,
                 cp_db: Path | None,
                 weights: dict[str, float],
                 split: str = "train") -> LossReport:
    # ----- discover iter prefix ----------------------------------------------
    stats_csvs = sorted(iter_dir.glob("*.chargingStats.csv"))
    if not stats_csvs:
        raise FileNotFoundError(f"no chargingStats.csv in {iter_dir}")
    stats_csv = stats_csvs[-1]
    iter_tag = stats_csv.name.split(".chargingStats.csv")[0]
    xy_candidates = [iter_dir / f"{iter_tag}.charger_occupancy_absolute.xy.gz",
                     iter_dir / f"{iter_tag}.charger_occupancy_absolute.xy"]
    xy_path = next((p for p in xy_candidates if p.exists()), None)
    if xy_path is None:
        raise FileNotFoundError(f"no charger_occupancy_absolute.xy[.gz] in {iter_dir}")

    # ----- load sim ----------------------------------------------------------
    ctypes = load_charger_types(chargers_xml)
    sessions = parse_charging_stats(stats_csv, ctypes)
    occ_by_charger = parse_station_occupancy(xy_path)

    # ----- load hold-outs ----------------------------------------------------
    agents_csv = splits_dir / f"agents_{split}.csv"
    stations_csv = splits_dir / f"stations_{split}.csv"
    crosswalk_csv = splits_dir / "sim_to_cp_crosswalk.csv"
    train_agents = load_id_set(agents_csv, "person_id") if agents_csv.exists() else set()
    train_cp_ids = load_id_set(stations_csv, "station_id") if stations_csv.exists() else set()

    # Translate CP station_ids → sim charger ids via the spatial crosswalk
    # produced by scripts/crosswalk_sim_chargepoint.py.  Without the crosswalk,
    # CP numeric ids ("125") can't be matched against sim ids ("l2_MD_0238").
    train_sim_chargers: set[str] = set()
    if train_cp_ids and crosswalk_csv.exists():
        cp_to_sim = load_cp_to_sim_crosswalk(crosswalk_csv)
        train_sim_chargers = {cp_to_sim[cp] for cp in train_cp_ids if cp in cp_to_sim}

    # ----- filter sim by hold-outs ------------------------------------------
    # Sessions: keep agent in split (population hold-out)
    if train_agents:
        sessions = [s for s in sessions if s.person_id in train_agents]
    # Occupancy: keep stations in split (spatial hold-out via crosswalk)
    if train_sim_chargers:
        occ_by_charger = {cid: rows for cid, rows in occ_by_charger.items()
                          if cid in train_sim_chargers}

    # ----- observed data ----------------------------------------------------
    obs_kwh = load_evwatts_session_kwh(evwatts_dir)
    obs_dcfc_share = load_evwatts_dcfc_share(evwatts_dir)
    obs_24hr = load_chargepoint_24hr_profile(cp_db, train_cp_ids)

    # ----- components -------------------------------------------------------
    sim_kwh = [s.energy_kwh for s in sessions if s.energy_kwh > 0]
    sim_dcfc_share = (
        sum(1 for s in sessions if s.charger_type.startswith("DCFC"))
        / max(1, len(sessions))
    )
    sim_24hr = to_24hr_profile(
        [pt for rows in occ_by_charger.values() for pt in rows])

    comp_kl = kde_kl_divergence(sim_kwh, obs_kwh) if obs_kwh else float("nan")
    comp_mape = mape(sim_24hr, obs_24hr) if obs_24hr else float("nan")
    comp_share = (abs(sim_dcfc_share - obs_dcfc_share)
                  if obs_dcfc_share is not None else float("nan"))

    # ----- aggregate (NaN components are dropped + weights renormalised) ----
    raw_components = {"kl": comp_kl, "mape": comp_mape, "share": comp_share}
    active = {k: v for k, v in raw_components.items() if not math.isnan(v)}
    if not active:
        loss = float("nan")
    else:
        w_active = {k: weights.get(k, 0.0) for k in active}
        w_sum = sum(w_active.values()) or 1.0
        loss = sum(active[k] * (w_active[k] / w_sum) for k in active)

    return LossReport(
        loss=loss,
        components=raw_components,
        weights=weights,
        counts={"sessions": len(sessions),
                "stations_in_split": len(occ_by_charger),
                "obs_sessions": len(obs_kwh),
                "obs_occ_bins": len(obs_24hr)},
        split=split,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_weights(s: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        k, v = tok.split("=")
        out[k.strip()] = float(v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iter-dir", required=True, type=Path,
                    help="output/.../ITERS/it.N")
    ap.add_argument("--chargers-xml", required=True, type=Path,
                    help="chargers file used for the sim (id -> type)")
    ap.add_argument("--splits", default=Path("splits"), type=Path)
    ap.add_argument("--evwatts-dir", type=Path, default=None)
    ap.add_argument("--cp-db", type=Path, default=None)
    ap.add_argument("--weights", default="kl=0.5,mape=0.4,share=0.1",
                    type=_parse_weights)
    ap.add_argument("--split", default="train", choices=["train", "dev", "test"])
    ap.add_argument("--unlock-test", action="store_true",
                    help="Required to read the test split (touch-once policy)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write LossReport JSON here (else stdout)")
    args = ap.parse_args()

    if args.split == "test" and not args.unlock_test:
        print("REFUSED: --split test requires --unlock-test (touch-once policy)",
              file=sys.stderr)
        return 2

    report = compute_loss(
        iter_dir=args.iter_dir,
        chargers_xml=args.chargers_xml,
        splits_dir=args.splits,
        evwatts_dir=args.evwatts_dir,
        cp_db=args.cp_db,
        weights=args.weights,
        split=args.split,
    )
    j = report.to_json()
    if args.out:
        args.out.write_text(j, encoding="utf-8")
        print(f"wrote {args.out}")
    print(j)
    return 0


if __name__ == "__main__":
    sys.exit(main())
