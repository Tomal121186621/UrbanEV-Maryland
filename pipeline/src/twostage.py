"""Two-stage factorized trip CVAE (structure -> magnitude).

The single-CVAE baseline forces ONE latent to encode both the day SKELETON
(count, activities, modes, departure) and the MAGNITUDES (distances, times), so the
distance tail is washed out and VMT undershoots. Here the day is factorized:

  Stage 1 (SKELETON):  a plain CVAE over the categorical structure (kchain, act_s,
      mode_s, first_dep_band), conditioned on the person+HH attributes.
  Stage 2 (MAGNITUDE): a plain CVAE over the per-slot numerics (logdist_s, travel_s,
      dwell_s), conditioned on the person attributes AND the Stage-1 skeleton.

Stage 2's whole latent serves magnitudes and it is told each slot's activity/mode, so
distance is conditioned on trip purpose (work -> long, errand -> short) and the tail is
recoverable. Both stages are plain CVAEs (MLP encoder -> Gaussian latent -> MLP decoder
with per-field heads). Feasibility is still enforced by src.trips.repair_day.
"""
from __future__ import annotations
import torch
import torch.nn.functional as F

from src.trips import SLOT_CAT, SLOT_NUM, COND_CAT, COND_NUM  # noqa: E402

# Stage-1 generates every categorical slot field; Stage-2 every numeric slot field.
SKEL_CAT = list(SLOT_CAT)
MAG_NUM = list(SLOT_NUM)


def person_cond(df, cond_codec, device):
    """Condition vector from person+HH attributes (shared by both stages)."""
    idx = cond_codec.encode(df, device=device)
    parts = [F.one_hot(idx[f], cond_codec.cardinalities()[f]).float() for f in COND_CAT]
    parts += [idx[f].unsqueeze(-1) for f in COND_NUM]
    return torch.cat(parts, dim=-1)


def skeleton_onehot(skel_idx, skel_codec, device):
    """One-hot the (encoded) skeleton categoricals for the Stage-2 condition.
    `skel_idx` maps each SKEL_CAT field -> LongTensor of category indices."""
    cards = skel_codec.cardinalities()
    return torch.cat([F.one_hot(skel_idx[f].to(device), cards[f]).float()
                      for f in SKEL_CAT], dim=-1)


def mag_cond(pcond, skel_idx, skel_codec, device):
    """Stage-2 condition = person attributes + Stage-1 skeleton (one-hot)."""
    return torch.cat([pcond, skeleton_onehot(skel_idx, skel_codec, device)], dim=-1)


@torch.no_grad()
def generate(df, cond_codec, skel_codec, mag_codec, skel_model, mag_model,
             device, temperature=1.0):
    """Sample skeletons then magnitudes for each person; return a `dec` dict
    (decoded values per field) ready for src.trips.repair_day(dec, i)."""
    pc = person_cond(df, cond_codec, device)
    n = pc.shape[0]
    s1 = skel_model.sample(n, cond=pc, device=device, temperature=temperature)
    mc = mag_cond(pc, s1, skel_codec, device)
    s2 = mag_model.sample(n, cond=mc, device=device, temperature=temperature)
    dec = {f: skel_codec.decode_cat(f, s1[f]) for f in SKEL_CAT}
    dec.update({f: mag_codec.decode_num(f, s2[f]) for f in MAG_NUM})
    return dec
