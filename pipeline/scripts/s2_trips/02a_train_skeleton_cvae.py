#!/usr/bin/env python3
"""
02a_train_skeleton_cvae.py — Stage 1 of the two-stage trip model.

Plain CVAE over the categorical day SKELETON (kchain, act_s, mode_s, first_dep_band),
conditioned on person+HH attributes. No numerics. Saves skeleton_cvae.pt + skel_codec.
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
from src.trips import build_daytable, COND_CAT, COND_NUM     # noqa: E402
from src.twostage import SKEL_CAT, person_cond               # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"
CKPT = ROOT / "pipeline/checkpoints"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 4711


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

    cond_codec = DataCodec(COND_CAT, COND_NUM).fit(trav)
    cond_codec.save(CKPT / "cond_codec.json")
    skel_codec = DataCodec(SKEL_CAT, []).fit(trav)
    tr_df, va_df = trav[trav.split == "train"], trav[trav.split == "val"]
    print(f"[data] train {len(tr_df):,} / val {len(va_df):,} on {DEVICE}")

    def prep(d):
        return (person_cond(d, cond_codec, DEVICE), skel_codec.encode(d, device=DEVICE),
                torch.tensor(d.wtperfin.to_numpy("float32"), device=DEVICE))
    cond_tr, enc_tr, w_tr = prep(tr_df)
    cond_va, enc_va, w_va = prep(va_df)
    cond_dim = cond_tr.shape[1]

    LATENT, HIDDEN = 24, 384
    model = MixedCVAE(skel_codec.cardinalities(), [], latent=LATENT, hidden=HIDDEN, cond_dim=cond_dim)
    bs = 4096
    def make(enc, w, cond, shuffle):
        nn = w.shape[0]
        def it():
            perm = torch.randperm(nn, device=DEVICE) if shuffle else torch.arange(nn, device=DEVICE)
            for i in range(0, nn, bs):
                idx = perm[i:i + bs]
                yield ({f: enc[f][idx] for f in SKEL_CAT}, w[idx], cond[idx])
        return it

    print(f"[train] skeleton CVAE (cond_dim={cond_dim}) ...")
    model, hist = train_cvae(model, make(enc_tr, w_tr, cond_tr, True), epochs=500, lr=1e-3,
                             beta_max=0.5, warmup=40, device=DEVICE, log_every=50,
                             val_batches_fn=make(enc_va, w_va, cond_va, False), patience=80)
    torch.save({"state_dict": model.state_dict(), "cat_cards": skel_codec.cardinalities(),
                "num_fields": [], "latent": LATENT, "hidden": HIDDEN, "cond_dim": cond_dim,
                "history": hist}, CKPT / "skeleton_cvae.pt")
    skel_codec.save(CKPT / "skel_codec.json")
    print(f"[save] {CKPT/'skeleton_cvae.pt'}")

    # quick skeleton marginal check (kchain) on held-out val
    model.eval()
    s = model.sample(len(va_df), cond=cond_va, device=DEVICE)
    ks = pd.Series([int(x) if str(x).isdigit() else 0 for x in skel_codec.decode_cat("kchain", s["kchain"])])
    print(f"[skeleton] kchain mean val-survey {va_df.kchain.mean():.2f} vs synth {ks.mean():.2f}")


if __name__ == "__main__":
    main()
