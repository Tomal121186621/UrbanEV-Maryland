#!/usr/bin/env python3
"""
03_synthesize.py — sample the synthetic MD population from the population CVAE.

Generates ~4.69M persons (the survey-weighted represented MD population), each with
household attributes + a home location (tract sampled within the generated county
proportional to survey household density; coordinate = tract centroid + jitter).
Person-level agents (the sim is agent-based; no household grouping needed).
Trips are generated later, ONLY for EV owners (03 is attributes only).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pipeline").is_dir())
sys.path.insert(0, str(ROOT / "pipeline"))
from src.encoders import DataCodec, band_to_age, age_to_band   # noqa: E402
from src.cvae import MixedCVAE                # noqa: E402

INTERIM = ROOT / "pipeline/data/interim"
CKPT = ROOT / "pipeline/checkpoints"
GEO = ROOT / "pipeline/data/geo/tract_centroids.parquet"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 4711
JITTER_M = 400.0   # in-tract coordinate jitter (std, metres)


def main():
    torch.manual_seed(SEED); rng = np.random.default_rng(SEED)
    codec = DataCodec.load(CKPT / "population_codec.json")
    ck = torch.load(CKPT / "population_cvae.pt", map_location=DEVICE, weights_only=False)
    model = MixedCVAE(ck["cat_cards"], ck["num_fields"], ck["latent"], ck["hidden"], 0,
                      prior_k=ck.get("prior_k", 0))
    model.load_state_dict(ck["state_dict"]); model.to(DEVICE).eval()

    # FULL Maryland population: scale each county to its census total by resampling
    # the CVAE pool per county (all 24 counties are survey-covered).
    census = pd.read_csv(ROOT / "pipeline/data/geo/md_county_pop.csv",
                         dtype={"fips": str}).set_index("fips")["pop"].to_dict()
    census_total = sum(census.values())
    N = int(census_total * 1.6)          # oversampled pool (rural counties are sparse)
    print(f"[sample] pool {N:,} on {DEVICE} -> resample to census {census_total:,} ...")
    chunks = []
    bs = 500_000
    done = 0
    while done < N:
        m = min(bs, N - done)
        s = model.sample(m, device=DEVICE)
        d = {f: codec.decode_cat(f, s[f]) for f in codec.cat_fields}
        d.update({f: codec.decode_num(f, s[f]) for f in codec.num_fields})
        chunks.append(pd.DataFrame(d))
        done += m
    pool = pd.concat(chunks, ignore_index=True)
    # expand the categorical age_band back to a numeric age (uniform within the band)
    pool["age"] = band_to_age(pool.age_band, rng)
    pool = pool.drop(columns=["age_band"])
    # Scale each county to its census total by resampling the CVAE pool (no IPF/raking —
    # marginals and county structure are LEARNED by the population CVAE itself, which is
    # trained with weighted data sampling so it honours the survey expansion weights).
    parts = []
    for fips, tgt in census.items():
        sub = pool[pool.home_county == fips]
        if len(sub) == 0:
            print(f"  WARN county {fips} absent from pool"); continue
        parts.append(sub.sample(int(tgt), replace=len(sub) < tgt, random_state=SEED))
    pop = pd.concat(parts, ignore_index=True)
    print(f"[census-scaled] {len(pop):,} persons across {pop.home_county.nunique()} counties")

    # ---- home location: sample a tract within the generated county ----
    cen = pd.read_parquet(GEO).set_index("tract_geoid")[["x", "y"]]
    hh = pd.read_parquet(INTERIM / "survey_hh.parquet")
    # per-county tract weights from survey household weights
    tw = (hh.groupby(["home_county", "home_tract"]).wthhfin.sum().reset_index())
    tw = tw[tw.home_tract.isin(cen.index)]
    county_tracts = {c: (g.home_tract.to_numpy(), (g.wthhfin / g.wthhfin.sum()).to_numpy())
                     for c, g in tw.groupby("home_county")}
    # fallback: any MD tract weighted by overall
    all_tr = tw.home_tract.to_numpy(); all_w = (tw.wthhfin / tw.wthhfin.sum()).to_numpy()

    home_tract = np.empty(len(pop), dtype=object)
    for c, sub in pop.groupby("home_county"):
        idx = sub.index.to_numpy()
        tr, w = county_tracts.get(str(c), (all_tr, all_w))
        home_tract[idx] = rng.choice(tr, size=len(idx), p=w)
    pop["home_tract"] = home_tract
    xy = cen.reindex(pop.home_tract).to_numpy()
    pop["home_x"] = xy[:, 0] + rng.normal(0, JITTER_M, len(pop))
    pop["home_y"] = xy[:, 1] + rng.normal(0, JITTER_M, len(pop))
    pop = pop.dropna(subset=["home_x", "home_y"]).reset_index(drop=True)

    # ---- structural consistency repair (hard logical rules the generative model can't
    # guarantee, analogous to trip feasibility): the CVAE bins/one-hots every field and
    # samples within bins, which fixes MARGINALS but not JOINT consistency, so it emits
    # impossible agents (e.g. licensed under-16s). Enforce: age<16 -> unlicensed + child
    # employment code (8); the child code never appears on 16+ (reassign from the adult
    # employment marginal). ----
    age_n = pd.to_numeric(pop.age, errors="coerce")
    kid = age_n < 16
    pop.loc[kid, "license"] = "2"
    pop.loc[kid, "employment_status"] = "8"
    adult_child = (age_n >= 16) & (pop.employment_status.astype(str) == "8")
    if adult_child.any():
        donor = pop.loc[(age_n >= 16) & (pop.employment_status.astype(str) != "8"),
                        "employment_status"].to_numpy()
        pop.loc[adult_child, "employment_status"] = rng.choice(donor, size=int(adult_child.sum()))
    print(f"[consistency] under-16 -> unlicensed+child-emp ({int(kid.sum()):,}); "
          f"reassigned {int(adult_child.sum()):,} adults miscoded child-employment")

    pop.insert(0, "person_id", ["md_%07d" % i for i in range(len(pop))])
    pop["synth_hh_id"] = pop.person_id       # 1 agent per synthetic unit
    pop.to_parquet(INTERIM / "synth_person.parquet", index=False)
    print(f"\n[save] synth_person.parquet — {len(pop):,} persons")
    print("county coverage:", pop.home_county.nunique(), "| licensed adults:",
          int(((pop.age >= 16) & (pop.license.astype(str) == "1")).sum()))


if __name__ == "__main__":
    main()
