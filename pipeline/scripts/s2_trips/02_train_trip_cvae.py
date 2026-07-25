#!/usr/bin/env python3
"""
02_train_trip_cvae.py — plain CONDITIONAL trip CVAE (GPU).

Generates a person's full day (activities, modes, distances, times) conditioned on
their household+person attributes. Fixed K_MAX=12 slots, PAD marks end-of-day.
Feasibility guaranteed by decode-time repair (src/trips.repair_day): home-anchored,
monotone times, <=24h. Trains only on feasible-chain travelers.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec              # noqa: E402
from src.cvae import MixedCVAE, train_cvae       # noqa: E402
from src.trips import (build_daytable, repair_day, K_MAX, PAD,     # noqa: E402
                       COND_CAT, COND_NUM, SLOT_CAT, SLOT_NUM)
from src.cvae import MixedCVAE as _MC             # noqa: E402  (NUM_MASK_KEY)

INTERIM = ROOT / "pipeline/data/interim"
CKPT = ROOT / "pipeline/checkpoints"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 4711


def make_cond(df, pop_codec, device):
    idx = pop_codec.encode(df, device=device)
    parts = [F.one_hot(idx[f], pop_codec.cardinalities()[f]).float() for f in COND_CAT]
    parts += [idx[f].unsqueeze(-1) for f in COND_NUM]
    return torch.cat(parts, dim=-1)


def main():
    torch.manual_seed(SEED); np.random.seed(SEED)
    hh = pd.read_parquet(INTERIM / "survey_hh.parquet")
    per = pd.read_parquet(INTERIM / "survey_person.parquet")
    trip = pd.read_parquet(INTERIM / "survey_trip.parquet")
    trav = per[per.n_trips > 0].merge(hh.drop(columns=["wthhfin","split"]), on="household_id")
    for c, hi in [("hhsize", 8), ("numworkers", 6), ("numvehicle", 6)]:
        trav[c] = pd.to_numeric(trav[c], errors="coerce").fillna(0).clip(0, hi).astype(int)
    trav["age"] = pd.to_numeric(trav.age, errors="coerce").clip(0, 100)

    day = build_daytable(trip, trav.person_id)
    trav = trav.merge(day, on="person_id")           # align order
    print(f"[data] {len(trav):,} travelers on {DEVICE}")

    # dedicated conditioning codec (age is numeric HERE, for the CVAE condition only;
    # the population model itself represents age as categorical bands)
    cond_codec = DataCodec(COND_CAT, COND_NUM).fit(trav)
    cond_codec.save(CKPT / "cond_codec.json")
    trip_codec = DataCodec(SLOT_CAT, SLOT_NUM).fit(trav)     # vocab on all
    tr_df, va_df = trav[trav.split == "train"], trav[trav.split == "val"]
    print(f"[data] train {len(tr_df):,} / val {len(va_df):,} travelers on {DEVICE}")

    def prep(d):
        # per-slot-numeric validity mask (num_fields order): a slot's numerics are
        # valid only when that slot is occupied (act != PAD); first_dep always valid.
        mcols = []
        for f in SLOT_NUM:
            if f == "first_dep":
                mcols.append(np.ones(len(d), bool))
            else:
                s = int(f.rsplit("_", 1)[1])
                mcols.append(d[f"act_{s}"].to_numpy() != PAD)
        mask = torch.tensor(np.stack(mcols, 1).astype("float32"), device=DEVICE)
        return (make_cond(d, cond_codec, DEVICE), trip_codec.encode(d, device=DEVICE),
                torch.tensor(d.wtperfin.to_numpy("float32"), device=DEVICE), mask)
    cond_tr, enc_tr, w_tr, m_tr = prep(tr_df)
    cond_va, enc_va, w_va, m_va = prep(va_df)
    cond_dim = cond_tr.shape[1]

    LATENT, HIDDEN = 24, 384
    model = MixedCVAE(trip_codec.cardinalities(), SLOT_NUM, latent=LATENT, hidden=HIDDEN,
                      cond_dim=cond_dim)
    model.num_weight = 4.0   # up-weight numeric recon (distance) vs the many categoricals
    bs = 4096
    def make(enc, w, cond, mask, shuffle):
        nn = w.shape[0]
        def it():
            perm = torch.randperm(nn, device=DEVICE) if shuffle else torch.arange(nn, device=DEVICE)
            for i in range(0, nn, bs):
                idx = perm[i:i + bs]
                b = {f: enc[f][idx] for f in SLOT_CAT + SLOT_NUM}
                b[_MC.NUM_MASK_KEY] = mask[idx]
                yield (b, w[idx], cond[idx])
        return it

    print(f"[train] trip CVAE (cond_dim={cond_dim}, train/val) ...")
    model, hist = train_cvae(model, make(enc_tr, w_tr, cond_tr, m_tr, True), epochs=500,
                             lr=1e-3, beta_max=0.5, warmup=40, device=DEVICE, log_every=50,
                             val_batches_fn=make(enc_va, w_va, cond_va, m_va, False), patience=80)
    model.calibrate_sigma(make(enc_tr, w_tr, cond_tr, m_tr, False), device=DEVICE)
    print("[calibrate] sample sigma:",
          {f: round(float(s), 3) for f, s in zip(SLOT_NUM, model.sample_sigma)})

    torch.save({"state_dict": model.state_dict(), "cat_cards": trip_codec.cardinalities(),
                "num_fields": SLOT_NUM, "latent": LATENT, "hidden": HIDDEN, "cond_dim": cond_dim,
                "history": hist}, CKPT / "trip_cvae.pt")
    trip_codec.save(CKPT / "trip_codec.json")
    print(f"[save] {CKPT/'trip_cvae.pt'}")

    # ---- validate on HELD-OUT VAL travelers (conditioned on their attributes) ----
    model.eval()
    nv = len(va_df)
    samp = model.sample(nv, cond=cond_va, device=DEVICE)
    dec = {f: (trip_codec.decode_cat(f, samp[f]) if f in SLOT_CAT
               else trip_codec.decode_num(f, samp[f])) for f in SLOT_CAT + SLOT_NUM}
    ntrips, dvmt, feasible = [], [], 0
    for i in range(nv):
        chain = repair_day(dec, i)
        if chain and chain[-1]["activity"] == 1 and all(
                chain[j]["dep_min"] <= chain[j + 1]["dep_min"] for j in range(len(chain) - 1)):
            feasible += 1
        ntrips.append(len(chain))
        dvmt.append(sum(c["distance"] for c in chain))
    vtrip = trip[trip.person_id.isin(va_df.person_id)]
    real_n = vtrip.groupby("person_id").size(); real_vmt = vtrip.groupby("person_id").distance.sum()
    print("\n[validate on held-out val] feasibility: %.1f%%" % (100 * feasible / nv))
    print(f"  trips/person  val-survey {real_n.mean():.2f}  synth {np.mean(ntrips):.2f}")
    print(f"  daily VMT/mi  val-survey {real_vmt.mean():.1f}  synth {np.mean(dvmt):.1f}")


if __name__ == "__main__":
    main()
