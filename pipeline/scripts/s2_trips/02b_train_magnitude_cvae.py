#!/usr/bin/env python3
"""
02b_train_magnitude_cvae.py — Stage 2 of the two-stage trip model.

Plain CVAE over the per-slot NUMERICS (logdist_s, travel_s, dwell_s), conditioned on
person attributes AND the Stage-1 skeleton (activities/modes/count/departure, one-hot).
The whole latent serves magnitudes and distance is conditioned on trip purpose, so the
long-trip tail (and hence VMT) is recoverable. Saves magnitude_cvae.pt + mag_codec.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec              # noqa: E402
from src.cvae import MixedCVAE, train_cvae       # noqa: E402
from src.trips import build_daytable, COND_CAT, COND_NUM, SLOT_CAT, PAD, K_MAX   # noqa: E402
from src.twostage import MAG_NUM, person_cond, mag_cond      # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"
CKPT = ROOT / "pipeline/checkpoints"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 4711
MASK_KEY = MixedCVAE.NUM_MASK_KEY


def main():
    torch.manual_seed(SEED); np.random.seed(SEED)
    hh = pd.read_parquet(INTERIM / "survey_hh.parquet")
    per = pd.read_parquet(INTERIM / "survey_person.parquet")
    trip = pd.read_parquet(INTERIM / "survey_trip.parquet")
    trav = per[per.n_trips > 0].merge(hh.drop(columns=["wthhfin", "split"]), on="household_id")
    for c, hi in [("hhsize", 8), ("numworkers", 6), ("numvehicle", 6)]:
        trav[c] = pd.to_numeric(trav[c], errors="coerce").fillna(0).clip(0, hi).astype(int)
    trav["age"] = pd.to_numeric(trav.age, errors="coerce").clip(0, 100)
    trav = trav.merge(build_daytable(trip, trav.person_id), on="person_id")

    cond_codec = DataCodec.load(CKPT / "cond_codec.json")
    skel_codec = DataCodec.load(CKPT / "skel_codec.json")
    mag_codec = DataCodec([], MAG_NUM).fit(trav)             # occupied-only numeric stats
    tr_df, va_df = trav[trav.split == "train"], trav[trav.split == "val"]
    print(f"[data] train {len(tr_df):,} / val {len(va_df):,} on {DEVICE}")

    def prep(d):
        pc = person_cond(d, cond_codec, DEVICE)
        skel_idx = skel_codec.encode(d, device=DEVICE)
        cond = mag_cond(pc, skel_idx, skel_codec, DEVICE)
        mcols = [d[f"act_{int(f.rsplit('_', 1)[1])}"].to_numpy() != PAD for f in MAG_NUM]
        mask = torch.tensor(np.stack(mcols, 1).astype("float32"), device=DEVICE)
        return (cond, mag_codec.encode(d, device=DEVICE),
                torch.tensor(d.wtperfin.to_numpy("float32"), device=DEVICE), mask)
    cond_tr, enc_tr, w_tr, m_tr = prep(tr_df)
    cond_va, enc_va, w_va, m_va = prep(va_df)
    cond_dim = cond_tr.shape[1]

    LATENT, HIDDEN = 16, 384
    model = MixedCVAE({}, MAG_NUM, latent=LATENT, hidden=HIDDEN, cond_dim=cond_dim)
    bs = 4096
    def make(enc, w, cond, mask, shuffle):
        nn = w.shape[0]
        def it():
            perm = torch.randperm(nn, device=DEVICE) if shuffle else torch.arange(nn, device=DEVICE)
            for i in range(0, nn, bs):
                idx = perm[i:i + bs]
                b = {f: enc[f][idx] for f in MAG_NUM}; b[MASK_KEY] = mask[idx]
                yield (b, w[idx], cond[idx])
        return it

    print(f"[train] magnitude CVAE (cond_dim={cond_dim}) ...")
    model, hist = train_cvae(model, make(enc_tr, w_tr, cond_tr, m_tr, True), epochs=500, lr=1e-3,
                             beta_max=0.5, warmup=40, device=DEVICE, log_every=50,
                             val_batches_fn=make(enc_va, w_va, cond_va, m_va, False), patience=80)
    model.calibrate_sigma(make(enc_tr, w_tr, cond_tr, m_tr, False), device=DEVICE)
    torch.save({"state_dict": model.state_dict(), "cat_cards": {}, "num_fields": MAG_NUM,
                "latent": LATENT, "hidden": HIDDEN, "cond_dim": cond_dim,
                "history": hist}, CKPT / "magnitude_cvae.pt")
    mag_codec.save(CKPT / "mag_codec.json")
    print(f"[save] {CKPT/'magnitude_cvae.pt'}")


if __name__ == "__main__":
    main()
