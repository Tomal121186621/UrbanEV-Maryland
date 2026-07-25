#!/usr/bin/env python3
"""
02e_train_trip_disc.py — FULLY CATEGORICAL trip CVAE (discretized magnitudes).

Every magnitude (distance/travel/dwell) is a categorical log-band, so softmax heads
reproduce the heavy tail (VMT) that Gaussian heads under-disperse. Conditioned on
person+HH attributes. Saves trip_disc_cvae.pt + trip_disc_codec.json + mag_edges.json.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec              # noqa: E402
from src.cvae import MixedCVAE, train_cvae       # noqa: E402
from src.trips import COND_CAT, COND_NUM         # noqa: E402
from src.tripdisc import build, fit_edges, SLOT_CAT, repair_disc, N_MAG_BINS   # noqa: E402
from src.twostage import person_cond             # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"; CKPT = ROOT / "pipeline/checkpoints"
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

    from src.trips import build_daytable
    edges = fit_edges(build_daytable(trip, trav.person_id))
    json.dump(edges, open(CKPT / "mag_edges.json", "w"))
    trav = trav.merge(build(trip, trav.person_id, edges), on="person_id")
    print(f"[data] {len(trav):,} travelers, {N_MAG_BINS} mag bins on {DEVICE}")

    cond_codec = DataCodec(COND_CAT, COND_NUM).fit(trav)
    cond_codec.save(CKPT / "cond_codec.json")
    disc_codec = DataCodec(SLOT_CAT, []).fit(trav)
    tr_df, va_df = trav[trav.split == "train"], trav[trav.split == "val"]
    print(f"[data] train {len(tr_df):,} / val {len(va_df):,}")

    def prep(d):
        return (person_cond(d, cond_codec, DEVICE), disc_codec.encode(d, device=DEVICE),
                torch.tensor(d.wtperfin.to_numpy("float32"), device=DEVICE))
    cond_tr, enc_tr, w_tr = prep(tr_df)
    cond_va, enc_va, w_va = prep(va_df)
    cond_dim = cond_tr.shape[1]

    LATENT, HIDDEN = 24, 512
    model = MixedCVAE(disc_codec.cardinalities(), [], latent=LATENT, hidden=HIDDEN,
                      cond_dim=cond_dim, dropout=0.15)   # tighten the overfit gap
    bs = 4096
    def make(enc, w, cond, shuffle):
        nn = w.shape[0]
        def it():
            perm = torch.randperm(nn, device=DEVICE) if shuffle else torch.arange(nn, device=DEVICE)
            for i in range(0, nn, bs):
                idx = perm[i:i + bs]
                yield ({f: enc[f][idx] for f in SLOT_CAT}, w[idx], cond[idx])
        return it

    print(f"[train] discretized trip CVAE (cond_dim={cond_dim}) ...")
    model, hist = train_cvae(model, make(enc_tr, w_tr, cond_tr, True), epochs=500, lr=1e-3,
                             beta_max=0.5, warmup=40, device=DEVICE, log_every=50,
                             val_batches_fn=make(enc_va, w_va, cond_va, False), patience=80)
    torch.save({"state_dict": model.state_dict(), "cat_cards": disc_codec.cardinalities(),
                "num_fields": [], "latent": LATENT, "hidden": HIDDEN, "cond_dim": cond_dim,
                "dropout": 0.15, "history": hist}, CKPT / "trip_disc_cvae.pt")
    disc_codec.save(CKPT / "trip_disc_codec.json")
    print(f"[save] {CKPT/'trip_disc_cvae.pt'}")

    # held-out val fidelity
    model.eval()
    rng = np.random.default_rng(SEED)
    s = model.sample(len(va_df), cond=cond_va, device=DEVICE)
    dec = {f: disc_codec.decode_cat(f, s[f]) for f in SLOT_CAT}
    ntr, vmt = [], []
    for i in range(len(va_df)):
        ch = repair_disc(dec, i, edges, rng); ntr.append(len(ch)); vmt.append(sum(c["distance"] for c in ch))
    vt = trip[trip.person_id.isin(va_df.person_id)]
    rn = vt.groupby("person_id").size(); rvmt = vt.groupby("person_id").distance.sum()
    print(f"[val] trips/person {np.mean(ntr):.2f} (survey {rn.mean():.2f})")
    print(f"      daily VMT {np.mean(vmt):.1f} (survey {rvmt.mean():.1f})  "
          f"per-trip {np.mean(vmt)/np.mean(ntr):.2f} (survey {rvmt.mean()/rn.mean():.2f})")


if __name__ == "__main__":
    main()
