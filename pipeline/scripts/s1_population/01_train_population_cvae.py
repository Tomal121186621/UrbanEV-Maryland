#!/usr/bin/env python3
"""
01_train_population_cvae.py — plain VAE for the synthetic population.

Unit = one PERSON with their household attributes attached (denormalized). This
gives EV-eligible agents directly (the sim is agent-based; household grouping is
not needed and the Lavan-Cirillo ownership is calibrated to MVA totals downstream).
Weighted by the person survey weight (wtperfin). Trains on GPU.

Fields:
  categorical: home_county, home_type, home_ownership, hh_income_detailed, hhsize,
    numworkers, numvehicle, numbicycle, gender, license, employment_status,
    home_office, charge_at_work
  numeric:     age
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec, age_to_band, band_to_age   # noqa: E402
from src.cvae import MixedCVAE, train_cvae    # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"
CKPT = ROOT / "pipeline/checkpoints"
CKPT.mkdir(exist_ok=True)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 4711

# age enters as a CATEGORICAL band (age_band) — a single Gaussian cannot represent the
# multimodal age structure (children + working-age + retirees). No numeric fields.
CAT = ["home_county", "home_type", "home_ownership", "hh_income_detailed",
       "hhsize", "numworkers", "numvehicle", "numbicycle",
       "gender", "license", "employment_status", "home_office", "charge_at_work",
       "age_band"]
NUM = []


def load_person_table():
    hh = pd.read_parquet(INTERIM / "survey_hh.parquet")
    per = pd.read_parquet(INTERIM / "survey_person.parquet")
    df = per.merge(hh.drop(columns=["wthhfin","split"]), on="household_id", how="inner")
    # clip count fields to survey caps (categorical stability)
    for c, hi in [("hhsize", 8), ("numworkers", 6), ("numvehicle", 6), ("numbicycle", 5)]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).clip(0, hi).astype(int)
    df["age"] = pd.to_numeric(df.age, errors="coerce").clip(0, 100)
    df["age_band"] = age_to_band(df.age)
    df = df[df.age_band >= 0]                          # drop unknown-age rows
    df = df.dropna(subset=[c for c in CAT if c != "age_band"] + ["wtperfin"])
    return df


def main():
    torch.manual_seed(SEED); np.random.seed(SEED)
    df = load_person_table()
    codec = DataCodec(CAT, NUM).fit(df)                 # fit vocab on ALL splits
    tr_df, va_df = df[df.split == "train"], df[df.split == "val"]
    print(f"[data] train {len(tr_df):,} / val {len(va_df):,} persons on {DEVICE}")
    enc_tr = codec.encode(tr_df, device=DEVICE); w_tr = torch.tensor(tr_df.wtperfin.to_numpy("float32"), device=DEVICE)
    enc_va = codec.encode(va_df, device=DEVICE); w_va = torch.tensor(va_df.wtperfin.to_numpy("float32"), device=DEVICE)

    LATENT, HIDDEN = 16, 256
    model = MixedCVAE(codec.cardinalities(), NUM, latent=LATENT, hidden=HIDDEN, cond_dim=0)
    bs = 4096
    def make(enc, w, shuffle):
        n = w.shape[0]
        def it():
            perm = torch.randperm(n, device=DEVICE) if shuffle else torch.arange(n, device=DEVICE)
            for i in range(0, n, bs):
                idx = perm[i:i + bs]
                yield {f: enc[f][idx] for f in CAT + NUM}, w[idx], None
        return it

    print("[train] population VAE (train/val) ...")
    model, hist = train_cvae(model, make(enc_tr, w_tr, True), epochs=400, lr=1e-3,
                             beta_max=1.0, warmup=30, device=DEVICE, log_every=25,
                             val_batches_fn=make(enc_va, w_va, False), patience=60)

    torch.save({"state_dict": model.state_dict(), "cat_cards": codec.cardinalities(),
                "num_fields": NUM, "latent": LATENT, "hidden": HIDDEN,
                "history": hist}, CKPT / "population_cvae.pt")
    codec.save(CKPT / "population_codec.json")
    print(f"[save] {CKPT/'population_cvae.pt'}")

    # marginal check on VALIDATION (held-out) survey vs synth (TVD)
    model.eval()
    samp = model.sample(200_000, device=DEVICE)
    print("\n[marginals] held-out-val survey vs synth TVD:")
    for f in CAT:
        real = va_df.groupby(f).wtperfin.sum(); real = real / real.sum()
        syn = pd.Series(codec.decode_cat(f, samp[f])).value_counts(normalize=True)
        real.index = [DataCodec._key(i) for i in real.index]
        print(f"  {f:20} TVD={0.5 * real.subtract(syn, fill_value=0).abs().sum():.3f}")
    age_syn = band_to_age(codec.decode_cat("age_band", samp["age_band"]), np.random.default_rng(SEED))
    print(f"  age (via bands)      mean survey {np.average(df.age, weights=df.wtperfin):.1f}"
          f" vs synth {age_syn.mean():.1f}")


if __name__ == "__main__":
    main()
