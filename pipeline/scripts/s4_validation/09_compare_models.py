#!/usr/bin/env python3
"""
09_compare_models.py — head-to-head trip fidelity of the plain-CVAE variants against
the WEIGHTED survey (the correct representative reference, not the unweighted mean):
  A. baseline   single CVAE, Gaussian magnitude heads (trip_cvae.pt)
  B. discrete   fully-categorical, discretized magnitude bands (trip_disc_cvae.pt)
Same 80k synth-person sample for both.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec          # noqa: E402
from src.cvae import MixedCVAE              # noqa: E402
from src.trips import repair_day, SLOT_CAT as B_CAT, SLOT_NUM as B_NUM   # noqa: E402
from src import tripdisc                     # noqa: E402
from src.twostage import person_cond         # noqa: E402

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


def summarize(tag, ntr, vmt, dists, deph, wtar, target):
    rn_w, rvmt_w, per_w, dwt = target
    print(f"\n[{tag}]  trips/person {np.mean(ntr):.2f} (survey-wt {rn_w:.2f})   "
          f"VMT {np.mean(vmt):.1f} (survey-wt {rvmt_w:.1f})   "
          f"per-trip {np.mean(vmt)/max(1e-9,np.mean(ntr)):.2f} (survey-wt {per_w:.2f})")
    dtv = num_tvd(dwt[0], np.clip(dists, 0, 50), dwt[1], np.linspace(0, 50, 41))
    print(f"        distance TVD (weighted) {dtv:.3f}   "
          f"VMT gap {100*(np.mean(vmt)-rvmt_w)/rvmt_w:+.1f}%")


def main():
    st = pd.read_parquet(INTERIM / "survey_trip.parquet")
    per = pd.read_parquet(INTERIM / "survey_person.parquet")
    syn = pd.read_parquet(INTERIM / "synth_person.parquet")
    cond_codec = DataCodec.load(CKPT / "cond_codec.json")

    # weighted survey targets
    trav = per[per.n_trips > 0].set_index("person_id")
    vmt_s = st.groupby("person_id").distance.sum(); ntr_s = st.groupby("person_id").size()
    w = trav.wtperfin.reindex(vmt_s.index).to_numpy()
    rn_w = np.average(ntr_s, weights=w); rvmt_w = np.average(vmt_s, weights=w)
    per_w = (vmt_s * w).sum() / (ntr_s * w).sum()
    dwt = (np.clip(st.distance, 0, 50).to_numpy(), st.wttrdfin.to_numpy())
    target = (rn_w, rvmt_w, per_w, dwt)
    print(f"WEIGHTED survey target: trips/person {rn_w:.2f}  VMT {rvmt_w:.1f}  per-trip {per_w:.2f}")

    samp = syn.sample(80_000, random_state=2).copy()
    for c in ["hhsize", "numworkers", "numvehicle", "age"]:
        samp[c] = pd.to_numeric(samp[c], errors="coerce").fillna(0)
    cond = person_cond(samp, cond_codec, DEV)

    # ---- A. baseline ----
    bm = load("trip_cvae.pt"); bcodec = DataCodec.load(CKPT / "trip_codec.json")
    s = bm.sample(len(samp), cond=cond, device=DEV)
    dec = {f: (bcodec.decode_cat(f, s[f]) if f in B_CAT else bcodec.decode_num(f, s[f]))
           for f in B_CAT + B_NUM}
    ntr, vmt, dists, deph = [], [], [], []
    for i in range(len(samp)):
        ch = repair_day(dec, i); ntr.append(len(ch)); vmt.append(sum(c["distance"] for c in ch))
        if ch:
            deph.append(ch[0]["dep_min"] / 60); dists += [c["distance"] for c in ch]
    summarize("A. baseline (Gaussian heads)", ntr, vmt, dists, deph, w, target)

    # ---- B. discretized ----
    dm = load("trip_disc_cvae.pt"); dcodec = DataCodec.load(CKPT / "trip_disc_codec.json")
    edges = json.load(open(CKPT / "mag_edges.json")); rng = np.random.default_rng(7)
    s = dm.sample(len(samp), cond=cond, device=DEV)
    dec = {f: dcodec.decode_cat(f, s[f]) for f in tripdisc.SLOT_CAT}
    ntr, vmt, dists, deph = [], [], [], []
    for i in range(len(samp)):
        ch = tripdisc.repair_disc(dec, i, edges, rng); ntr.append(len(ch)); vmt.append(sum(c["distance"] for c in ch))
        if ch:
            deph.append(ch[0]["dep_min"] / 60); dists += [c["distance"] for c in ch]
    summarize("B. discretized (categorical bands)", ntr, vmt, dists, deph, w, target)


if __name__ == "__main__":
    main()
