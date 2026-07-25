"""Plain conditional VAE for mixed categorical + numeric tabular data.

Textbook CVAE — MLP encoder -> diagonal Gaussian latent -> MLP decoder with one
head per field (softmax cross-entropy for categoricals, Gaussian NLL for numerics).
Weighted ELBO (survey weights), linear beta-warmup. Optional condition vector `c`
(concatenated to encoder input and to the latent before decoding) makes it a CVAE;
with cond_dim=0 it is a plain VAE. No hierarchy, no attention. GPU-ready.
"""
from __future__ import annotations
import math
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


def mlp(sizes, act=nn.SiLU, out_act=None, dropout=0.0):
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers += [nn.LayerNorm(sizes[i + 1]), act()]
            if dropout > 0:
                layers.append(nn.Dropout(dropout))
    if out_act is not None:
        layers.append(out_act())
    return nn.Sequential(*layers)


class MixedCVAE(nn.Module):
    def __init__(self, cat_cards: dict, num_fields: list, latent=16, hidden=256,
                 cond_dim=0, emb_cap=32, split_decoder=False, dropout=0.0, prior_k=0):
        super().__init__()
        self.cat_fields = list(cat_cards)
        self.num_fields = list(num_fields)
        self.cond_dim = cond_dim
        self.latent = latent
        # LEARNED GMM PRIOR (prior_k>0): the N(0,I) prior can't allocate enough mass to
        # rare modes (e.g. children), so prior sampling under-generates them regardless
        # of loss/sample weighting. A mixture prior trained jointly reshapes p(z) to the
        # aggregate posterior — end-to-end learned, no post-hoc fitting. prior_k=0 keeps
        # the plain N(0,I) prior (closed-form KL).
        self.prior_k = int(prior_k)
        if self.prior_k > 0:
            self.prior_mean = nn.Parameter(torch.randn(self.prior_k, latent) * 0.6)
            self.prior_logvar = nn.Parameter(torch.zeros(self.prior_k, latent))
            self.prior_logit = nn.Parameter(torch.zeros(self.prior_k))
        self.split_decoder = bool(split_decoder and num_fields)
        self.embs = nn.ModuleDict()
        in_dim = cond_dim
        for f, k in cat_cards.items():
            d = min(emb_cap, max(4, int(round(k ** 0.5)) + 2))
            self.embs[f] = nn.Embedding(k, d)
            in_dim += d
        in_dim += len(num_fields)
        self.enc = mlp([in_dim, hidden, hidden], dropout=dropout)
        self.to_mu = nn.Linear(hidden, latent)
        self.to_lv = nn.Linear(hidden, latent)
        self.dec = mlp([latent + cond_dim, hidden, hidden], dropout=dropout)
        # FACTORED decoder: a separate MLP branch feeds the numeric heads so the
        # distance/travel/dwell reconstruction is not starved by the gradients of the
        # many categorical cross-entropy heads sharing one trunk (decouples VMT from
        # count/departure). Still a plain CVAE — just two decoder branches.
        self.dec_num = mlp([latent + cond_dim, hidden, hidden], dropout=dropout) if self.split_decoder else None
        self.cat_heads = nn.ModuleDict({f: nn.Linear(hidden, k) for f, k in cat_cards.items()})
        self.num_head = nn.Linear(hidden, len(num_fields)) if num_fields else None
        # TRAINING uses fixed unit variance (plain MSE on z-scored targets) — avoids
        # the learned-variance collapse that shrinks sampled numerics toward the mean.
        self.num_sigma = 1.0
        # numeric reconstruction weight: the ELBO sums one CE per categorical field
        # (many) but only a few numeric MSE terms, so the shared decoder starves the
        # distance head (VMT dips). >1 rebalances toward the numerics. Plain-CVAE knob.
        self.num_weight = 1.0
        # SAMPLING uses a per-field residual std calibrated AFTER training
        # (calibrate_sigma). Injecting the full marginal variance (1.0) at sample time
        # doubles the spread and, through the convex expm1 on log-distance, inflates
        # the mean (Jensen). The residual std is < 1 whenever the decoder explains any
        # variance, so calibrated sampling reproduces the true (skewed) distribution.
        self.register_buffer("sample_sigma", torch.ones(max(1, len(num_fields))))

    NUM_MASK_KEY = "__num_mask__"   # optional (n, F) validity mask in num_fields order

    def _feat(self, batch, cond):
        parts = []
        if cond is not None and self.cond_dim:
            parts.append(cond)
        for f in self.cat_fields:
            parts.append(self.embs[f](batch[f]))
        for f in self.num_fields:
            parts.append(batch[f].unsqueeze(-1))
        return torch.cat(parts, dim=-1)

    def encode(self, batch, cond=None):
        h = self.enc(self._feat(batch, cond))
        return self.to_mu(h), self.to_lv(h).clamp(-8, 8)

    def decode(self, z, cond=None):
        if cond is not None and self.cond_dim:
            z = torch.cat([z, cond], dim=-1)
        h = self.dec(z)
        cat_logits = {f: self.cat_heads[f](h) for f in self.cat_fields}
        if self.num_head is not None:
            h_num = self.dec_num(z) if self.dec_num is not None else h
            num_mean = self.num_head(h_num)
        else:
            num_mean = None
        return cat_logits, num_mean

    def forward(self, batch, cond=None):
        mu, lv = self.encode(batch, cond)
        z = mu + torch.randn_like(mu) * (0.5 * lv).exp()
        return self.decode(z, cond), mu, lv, z

    def _prior_logprob(self, z):
        """log p(z) under the learned GMM prior — (n,) log-density."""
        logw = torch.log_softmax(self.prior_logit, dim=0)                 # (k,)
        pm = self.prior_mean.unsqueeze(0); plv = self.prior_logvar.unsqueeze(0)  # (1,k,d)
        zz = z.unsqueeze(1)                                               # (n,1,d)
        comp = -0.5 * (math.log(2 * math.pi) + plv + (zz - pm) ** 2 / plv.exp())
        return torch.logsumexp(logw + comp.sum(-1), dim=1)               # (n,)

    def elbo(self, batch, cond=None, w=None, beta=1.0):
        (cat_logits, num_mean), mu, lv, z = self.forward(batch, cond)
        n = mu.shape[0]
        if w is None:
            w = torch.ones(n, device=mu.device)
        w = w / w.mean()
        rec = torch.zeros(n, device=mu.device)
        for f in self.cat_fields:
            rec = rec + F.cross_entropy(cat_logits[f], batch[f], reduction="none")
        if self.num_fields:
            tgt = torch.stack([batch[f] for f in self.num_fields], dim=-1)
            se = 0.5 * ((tgt - num_mean) ** 2) / (self.num_sigma ** 2)
            mask = batch.get(self.NUM_MASK_KEY)
            if mask is not None:
                se = se * mask               # PAD-slot numerics don't train the mean
            rec = rec + self.num_weight * se.sum(-1)
        if self.prior_k > 0:                       # KL(q||GMM prior), MC estimate at z
            log_q = (-0.5 * (math.log(2 * math.pi) + lv + (z - mu) ** 2 / lv.exp())).sum(-1)
            kl = log_q - self._prior_logprob(z)
        else:
            kl = -0.5 * (1 + lv - mu.pow(2) - lv.exp()).sum(-1)
        loss = (w * (rec + beta * kl)).mean()
        return loss, (w * rec).mean().item(), (w * kl).mean().item()

    @torch.no_grad()
    def sample(self, n, cond=None, device="cpu", temperature=1.0, forbid=None):
        if self.prior_k > 0:                       # draw z from the learned GMM prior
            comp = torch.multinomial(torch.softmax(self.prior_logit, 0), n, replacement=True)
            pm = self.prior_mean[comp]; pstd = (0.5 * self.prior_logvar[comp]).exp()
            z = (pm + torch.randn(n, self.latent, device=self.prior_mean.device) * pstd).to(device)
        else:
            z = torch.randn(n, self.latent, device=device)
        cat_logits, num_mean = self.decode(z, cond)
        out = {}
        for f in self.cat_fields:
            logit = cat_logits[f]
            bad = [0] + list(forbid.get(f, [])) if forbid else [0]   # OOV (+ PAD) never generated
            bad = [b for b in bad if 0 <= b < logit.shape[-1]]
            if bad and logit.shape[-1] > len(bad):
                logit = logit.clone(); logit[:, bad] = -1e9
            p = torch.softmax(logit / temperature, dim=-1)
            out[f] = torch.multinomial(p, 1).squeeze(-1)
        if self.num_fields:
            sig = self.sample_sigma.to(num_mean.device).unsqueeze(0)  # (1, F)
            samp = num_mean + torch.randn_like(num_mean) * sig * temperature
            for i, f in enumerate(self.num_fields):
                out[f] = samp[:, i]
        return out

    @torch.no_grad()
    def calibrate_sigma(self, batches_fn, device="cpu"):
        """Set per-field sample_sigma to the empirical std of the decoder residual
        (z-scored target minus posterior-mean prediction) over a data iterator.
        Call AFTER training so sampled numerics carry the true residual spread — not
        the full marginal variance — which keeps log-distance from inflating on expm1."""
        if not self.num_fields:
            return self
        self.eval()
        sse = torch.zeros(len(self.num_fields), device=device)
        cnt = torch.zeros(len(self.num_fields), device=device)
        for batch, _w, cond in batches_fn():
            mu, _ = self.encode(batch, cond)
            _, num_mean = self.decode(mu, cond)          # posterior-mean reconstruction
            tgt = torch.stack([batch[f] for f in self.num_fields], dim=-1)
            mask = batch.get(self.NUM_MASK_KEY)
            if mask is None:
                mask = torch.ones_like(tgt)
            sse += (((tgt - num_mean) ** 2) * mask).sum(0)   # occupied-slot residual only
            cnt += mask.sum(0)
        self.sample_sigma = (sse / cnt.clamp(min=1)).sqrt().cpu()
        return self


@torch.no_grad()
def eval_cvae(model, batches_fn, beta=1.0):
    """Mean loss/rec/kl over a (val/test) batch iterator — no grad."""
    model.eval(); tot = rec_s = kl_s = nb = 0
    for batch, w, cond in batches_fn():
        loss, rec, kl = model.elbo(batch, cond, w, beta)
        tot += loss.item(); rec_s += rec; kl_s += kl; nb += 1
    return tot / nb, rec_s / nb, kl_s / nb


def train_cvae(model, batches_fn, epochs, lr=1e-3, beta_max=1.0, warmup=10,
               device="cuda", log_every=5, val_batches_fn=None, patience=None):
    """Train; if val_batches_fn given, track validation loss (early stopping on it).
    Returns (model, history) where history has train/val loss/rec/kl per epoch."""
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    hist = {k: [] for k in ("epoch", "beta", "tr_loss", "tr_rec", "tr_kl",
                            "va_loss", "va_rec", "va_kl")}
    best_va, best_state, bad = float("inf"), None, 0
    for ep in range(epochs):
        beta = beta_max * min(1.0, (ep + 1) / max(1, warmup))
        model.train(); tot = rec_s = kl_s = nb = 0
        for batch, w, cond in batches_fn():
            loss, rec, kl = model.elbo(batch, cond, w, beta)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            tot += loss.item(); rec_s += rec; kl_s += kl; nb += 1
        hist["epoch"].append(ep); hist["beta"].append(beta)
        hist["tr_loss"].append(tot / nb); hist["tr_rec"].append(rec_s / nb); hist["tr_kl"].append(kl_s / nb)
        if val_batches_fn is not None:
            # evaluate at FIXED beta_max: mid-warmup betas make va_loss (rec + beta*kl)
            # incomparable across epochs — a warmup-era epoch would otherwise always win
            # best-checkpoint and freeze an under-annealed model.
            vl, vr, vk = eval_cvae(model, val_batches_fn, beta_max)
            hist["va_loss"].append(vl); hist["va_rec"].append(vr); hist["va_kl"].append(vk)
            if ep < warmup:
                pass                                     # no best-tracking during warmup
            elif vl < best_va - 1e-4:
                best_va, best_state, bad = vl, {k: v.detach().clone() for k, v in model.state_dict().items()}, 0
            else:
                bad += 1
        else:
            for k in ("va_loss", "va_rec", "va_kl"): hist[k].append(float("nan"))
        if ep % log_every == 0 or ep == epochs - 1:
            va = hist["va_loss"][-1]
            print(f"  ep {ep:3d}  tr {tot/nb:8.3f}  va {va:8.3f}  rec {rec_s/nb:7.3f}  "
                  f"kl {kl_s/nb:6.3f}  beta {beta:.2f}", flush=True)
        if patience and bad >= patience:
            print(f"  early stop at ep {ep} (best va {best_va:.3f})"); break
    if best_state is not None:
        model.load_state_dict(best_state)   # restore best-val checkpoint
    return model, hist
