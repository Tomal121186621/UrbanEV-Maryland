#!/usr/bin/env python3
"""
08_compare_twostage.py — trip fidelity of the TWO-STAGE model vs the single-CVAE
baseline, on the same 80k synth-person sample and survey reference used by 07.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec          # noqa: E402
from src.cvae import MixedCVAE              # noqa: E402
from src.trips import repair_day            # noqa: E402
from src.twostage import generate           # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"; CKPT = ROOT / "pipeline/checkpoints"
DEV = "cuda" if torch.cuda.is_available() else "cpu"


def tvd(a, b):
    idx = sorted(set(a.index) | set(b.index))
    return 0.5 * float(np.abs(a.reindex(idx, fill_value=0) - b.reindex(idx, fill_value=0)).sum())


def num_tvd(real, syn_, wr, bins):
    hr, _ = np.histogram(real, bins=bins, weights=wr, density=True)
    hs, _ = np.histogram(syn_, bins=bins, density=True)
    return 0.5 * float((np.abs(hr - hs) * np.diff(bins)).sum())


def load(name):
    ck = torch.load(CKPT / name, map_location=DEV, weights_only=False)
    m = MixedCVAE(ck["cat_cards"], ck["num_fields"], ck["latent"], ck["hidden"], ck["cond_dim"])
    m.load_state_dict(ck["state_dict"]); m.to(DEV).eval(); return m


def main():
    st = pd.read_parquet(INTERIM / "survey_trip.parquet")
    syn = pd.read_parquet(INTERIM / "synth_person.parquet")
    cond_codec = DataCodec.load(CKPT / "cond_codec.json")
    skel_codec = DataCodec.load(CKPT / "skel_codec.json")
    mag_codec = DataCodec.load(CKPT / "mag_codec.json")
    skel_model, mag_model = load("skeleton_cvae.pt"), load("magnitude_cvae.pt")

    samp = syn.sample(80_000, random_state=2).copy()
    for c in ["hhsize", "numworkers", "numvehicle", "age"]:
        samp[c] = pd.to_numeric(samp[c], errors="coerce").fillna(0)
    dec = generate(samp, cond_codec, skel_codec, mag_codec, skel_model, mag_model, DEV)

    ntr, vmt, deph, dists, modes, acts, dwells, feas = [], [], [], [], [], [], [], 0
    for i in range(len(samp)):
        ch = repair_day(dec, i); ntr.append(len(ch)); vmt.append(sum(c["distance"] for c in ch))
        if ch and ch[-1]["activity"] == 1:
            feas += 1
        if ch:
            deph.append(ch[0]["dep_min"] / 60)
            for c in ch:
                dists.append(c["distance"]); modes.append(c["mode"]); acts.append(c["activity"])
                dwells.append(c["dwell_min"])
    rn = st.groupby("person_id").size(); rvmt = st.groupby("person_id").distance.sum()
    wtr = st.wttrdfin.to_numpy()

    def catt(col, syn_list):
        rr = st.groupby(st[col].astype(int)).wttrdfin.sum(); rr = rr / rr.sum()
        ss = pd.Series([int(v) for v in syn_list]).value_counts(normalize=True)
        return tvd(rr.rename(index=str), ss.rename(index=str))

    m_tvd = {
        "trips_per_person": num_tvd(rn, np.array(ntr), np.ones(len(rn)), np.arange(0, 15)),
        "travel_mode": catt("travel_mode", modes),
        "destination_activity": catt("d_activity", acts),
        "distance": num_tvd(np.clip(st.distance, 0, 50), np.clip(dists, 0, 50), wtr, np.linspace(0, 50, 41)),
        "departure_hour": num_tvd(st.dep_min / 60, np.array(deph), wtr, np.arange(0, 25)),
        "dwell_time": num_tvd(np.clip(st.dwell_min, 0, 600), np.clip(dwells, 0, 600), wtr, np.linspace(0, 600, 41)),
    }
    print(f"[two-stage] feasibility {100*feas/len(samp):.1f}%")
    print(f"  trips/person survey {rn.mean():.2f} vs synth {np.mean(ntr):.2f}")
    print(f"  daily VMT    survey {rvmt.mean():.1f} vs synth {np.mean(vmt):.1f} mi "
          f"(per-trip {rvmt.mean()/rn.mean():.2f} vs {np.mean(vmt)/max(1e-9,np.mean(ntr)):.2f})")
    print("  TVDs:", {k: round(v, 3) for k, v in m_tvd.items()})

    # baseline numbers from its archived summary
    base = (ROOT / "pipeline/output/validation_baseline_shared_decoder/validation_summary.md")
    print("\n[baseline single-CVAE] (from archived summary):")
    if base.exists():
        for ln in base.read_text().splitlines():
            if any(k in ln for k in ("trips_per_person", "travel_mode", "destination_activity",
                                     "| distance", "departure_hour", "dwell_time", "daily VMT")):
                print("  " + ln.strip())


if __name__ == "__main__":
    main()
