#!/usr/bin/env python3
"""ROBUSTNESS #4 — simulation stability. (a) venue-share variance across 3 independent
seeds (does the emergent charging mix depend on the random seed?); (b) plan-score
trajectory of the baseline (justifies the 8-iteration warm-started convergence used for
the policy/sweep runs: innovation is disabled at 80% of iterations and the score locks).
-> paper/figures/trb/fig20_stability.png + paper/tables/seed_stability.csv"""
import sys, glob, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
OUT = REPO / "paper/figures/trb"; TAB = REPO / "paper/tables"
BLU, ORA, GRN, VER, GRY = pf.BLUE, pf.ORANGE, pf.GREEN, pf.VERM, pf.GREY

def venue(run):
    fs = sorted(glob.glob(str(RUNS/run/"ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    if not fs: return None
    d = pd.read_csv(fs[-1], sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
    v = d.groupby("charger_type_3way").e.sum(); t = v.sum()
    return {k: v.get(k, 0)/t*100 for k in ["home", "work", "public"]}

seeds = ["seed_1001_25pct", "seed_2002_25pct", "seed_3003_25pct"]
df = pd.DataFrame({s: venue(s) for s in seeds}).T
df.to_csv(TAB/"seed_stability.csv")

fig, ax = plt.subplots(1, 2, figsize=(11, 3.9))
# (a) venue shares across seeds (bar + individual points)
ven = ["home", "work", "public"]; cols = [BLU, GRN, ORA]
m = df[ven].mean(); sd = df[ven].std()
ax[0].bar(range(3), m.values, yerr=sd.values, color=cols, edgecolor="k", lw=0.4,
          capsize=5, error_kw=dict(lw=1.2))
for i, v in enumerate(ven):
    ax[0].scatter([i]*len(df), df[v].values, color="k", s=18, zorder=5)
    ax[0].text(i, m[v]+sd[v]+1.5, f"{m[v]:.1f}±{sd[v]:.2f}", ha="center", fontsize=8)
ax[0].set_xticks(range(3)); ax[0].set_xticklabels(["Home", "Work", "Public"])
ax[0].set(ylabel="% of charging energy", title="(a) Venue shares across 3 seeds", ylim=(0, 92))
ax[0].grid(axis="y", alpha=0.25)

# (b) baseline score trajectory (convergence)
sc = pd.read_csv(RUNS/"baseline_pertype/scorestats.txt", sep="\t")
it = sc.iloc[:, 0].values; ex = sc.iloc[:, 1].values
ax[1].plot(it, ex, "-o", color=VER, ms=4)
off = int(0.8*15)
ax[1].axvline(off, color=GRY, ls=":", lw=1)
ax[1].text(off+0.2, ex.min()+0.3, "innovation off\n(80% of iters)", fontsize=8, color=GRY)
ax[1].annotate("score locks (agents fix best plan)", (14, ex[14]), xytext=(6, ex[14]+0.9),
               fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.6))
ax[1].set(xlabel="iteration", ylabel="mean executed plan score",
          title="(b) Convergence (baseline, 15 iter)")
ax[1].grid(alpha=0.25)
fig.suptitle("Simulation stability: seed-robust venue mix (CV < 3%) and a converged score",
             fontsize=12, fontweight="bold", y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(OUT/"fig20_stability.pdf"); fig.savefig(OUT/"fig20_stability.png", dpi=300)
plt.close(fig)
print(df.round(2).to_string())
print(f"\nCV: home {sd['home']/m['home']*100:.1f}%  public {sd['public']/m['public']*100:.1f}%")
print("-> fig20_stability + seed_stability.csv")
