"""DataCodec — encode a mixed categorical/numeric table to model tensors and back.

Categoricals -> contiguous integer indices (0..K-1), with an OOV bucket at index 0.
Numerics    -> z-score standardized (mean/std stored).
Everything JSON-serializable so a codec round-trips with a checkpoint.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import torch

# Age is modelled as CATEGORICAL BANDS (not a single Gaussian): the population age
# distribution is multimodal (children + working-age + a retiree plateau), which one
# Gaussian numeric head cannot represent. Band edges respect the driving/EV-eligibility
# threshold at 16. Synthesis samples a uniform age within the decoded band.
AGE_EDGES = np.array([0, 5, 10, 16, 18, 25, 35, 45, 55, 65, 75, 85, 200])
N_AGE_BANDS = len(AGE_EDGES) - 1


def age_to_band(age) -> np.ndarray:
    """Map numeric age -> band index 0..N_AGE_BANDS-1 (NaN-safe -> -1)."""
    a = pd.to_numeric(age, errors="coerce").to_numpy(float)
    b = np.digitize(a, AGE_EDGES[1:-1], right=False)
    b[np.isnan(a)] = -1
    return b.astype(int)


def band_to_age(bands, rng) -> np.ndarray:
    """Expand band indices back to a numeric age ~ Uniform[edge_lo, edge_hi)."""
    bands = np.asarray([int(b) if str(b).lstrip("-").isdigit() else 0 for b in bands])
    bands = np.clip(bands, 0, N_AGE_BANDS - 1)
    lo = AGE_EDGES[bands]; hi = np.minimum(AGE_EDGES[bands + 1], 100)
    return (lo + rng.random(len(bands)) * (hi - lo)).round().astype(int)


class DataCodec:
    def __init__(self, cat_fields, num_fields):
        self.cat_fields = list(cat_fields)   # column names
        self.num_fields = list(num_fields)
        self.cats = {}      # field -> list of category values (index 0 = OOV/pad)
        self.num_stats = {}  # field -> (mean, std)

    def fit(self, df: pd.DataFrame):
        for c in self.cat_fields:
            vals = sorted(pd.unique(df[c].dropna()))
            self.cats[c] = ["__OOV__"] + [self._key(v) for v in vals]
        for c in self.num_fields:
            x = pd.to_numeric(df[c], errors="coerce").astype(float)
            self.num_stats[c] = (float(x.mean()), float(x.std() or 1.0))
        return self

    @staticmethod
    def _key(v):
        # normalize numeric-looking keys to int-strings for stable lookup
        try:
            f = float(v)
            return str(int(f)) if f == int(f) else str(f)
        except (ValueError, TypeError):
            return str(v)

    def cardinalities(self):
        return {c: len(self.cats[c]) for c in self.cat_fields}

    def encode(self, df: pd.DataFrame, device="cpu"):
        out = {}
        for c in self.cat_fields:
            idx = {v: i for i, v in enumerate(self.cats[c])}
            col = df[c].map(lambda v: idx.get(self._key(v), 0)).fillna(0).astype("int64")
            out[c] = torch.tensor(col.to_numpy(), device=device)
        for c in self.num_fields:
            m, s = self.num_stats[c]
            x = pd.to_numeric(df[c], errors="coerce").fillna(m).astype("float32")
            out[c] = torch.tensor(((x - m) / s).to_numpy(), device=device)
        return out

    def decode_cat(self, field, idx_tensor):
        cats = self.cats[field]
        a = idx_tensor.detach().cpu().numpy()
        return np.array([cats[min(max(int(i), 0), len(cats) - 1)] for i in a])

    def decode_num(self, field, val_tensor):
        m, s = self.num_stats[field]
        return val_tensor.detach().cpu().numpy() * s + m

    def to_dict(self):
        return {"cat_fields": self.cat_fields, "num_fields": self.num_fields,
                "cats": self.cats, "num_stats": self.num_stats}

    @classmethod
    def from_dict(cls, d):
        o = cls(d["cat_fields"], d["num_fields"])
        o.cats = d["cats"]; o.num_stats = {k: tuple(v) for k, v in d["num_stats"].items()}
        return o

    def save(self, path):
        open(path, "w").write(json.dumps(self.to_dict()))

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.load(open(path)))
