#!/usr/bin/env python3
"""R0 diagnostic — does the charging venue mix keep responding to a +150c public surcharge
past iteration 8, or does it plateau? Compares the 25% baseline vs 25% +150c run (same
warm-start, 50 iters). If the +150c public share keeps falling well past iter 8 and only
settles later, the 8-iteration full sweep UNDER-converged the response (model IS sensitive,
just needs more iters). If it plateaus by ~iter 8-10 near 9.8%, the inelasticity is real.
-> paper/figures/trb/fig21_convergence_diagnostic.png"""
import sys, glob, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
RUNS = ROOT / "scenarios/maryland/output/runs_2026"
OUT = REPO / "paper/figures/trb"
BLU, VER, GRY = pf.BLUE, pf.VERM, pf.GREY

def traj(run):
    fs = sorted(glob.glob(str(RUNS/run/"ITERS/it.*/*.charging_sessions.csv")),
                key=lambda p: int(p.split("it.")[1].split("/")[0]))
    its, sh = [], []
    for f in fs:
        d = pd.read_csv(f, sep=";"); d["e"] = pd.to_numeric(d.energy_kwh, errors="coerce")
        its.append(int(f.split("it.")[1].split("/")[0]))
        sh.append(d[d.charger_type_3way == "public"].e.sum()/d.e.sum()*100)
    return np.array(its), np.array(sh)

ib, sb = traj("diag_base_25pct")
ip, sp = traj("diag_pub150_25pct")
print(f"baseline: {len(ib)} iters, final public {sb[-1]:.1f}%" if len(ib) else "baseline: no data yet")
print(f"+150c:    {len(ip)} iters, final public {sp[-1]:.1f}%" if len(ip) else "+150c: no data yet")

if len(ib) < 3 or len(ip) < 3:
    print("[wait] runs still early; rerun when more iterations complete."); sys.exit(0)

fig, ax = pf.newfig(7.0, 4.4)
ax.plot(ib, sb, "-o", color=BLU, ms=4, lw=2, label="baseline (per-type prices)")
ax.plot(ip, sp, "-s", color=VER, ms=4, lw=2, label="+150¢/kWh public surcharge")
ax.axvline(8, color=GRY, ls=":", lw=1.2)
ax.text(8.3, ax.get_ylim()[1]*0.96, "full-sweep cutoff\n(8 iters)", fontsize=8, color=GRY, va="top")
# mark where +150c settles
if len(ip) > 10:
    tail = sp[-5:]; conv = tail.mean()
    ax.axhline(conv, color=VER, ls="--", lw=0.8, alpha=0.6)
    ax.text(len(ip)*0.6, conv+0.15, f"converged ≈ {conv:.1f}%", color=VER, fontsize=8.5)
    at8 = sp[np.argmin(np.abs(ip-8))]
    ax.annotate(f"at iter 8: {at8:.1f}%\nconverged: {conv:.1f}%\n→ {abs(at8-conv):.1f} pp {'MORE' if conv<at8 else 'less'} response",
                (8, at8), xytext=(15, at8+1.2), fontsize=8, arrowprops=dict(arrowstyle="->", lw=0.6))
ax.set(xlabel="iteration", ylabel="public share of charging energy (%)",
       title="Convergence diagnostic: does the price response keep growing past iter 8?")
ax.legend(fontsize=9); ax.grid(alpha=0.25)
pf.save(fig, OUT, "fig21_convergence_diagnostic")
print("-> fig21_convergence_diagnostic.png")
if len(ip) > 10:
    print(f"\nVERDICT: +150c public share  iter8={at8:.1f}%  converged={conv:.1f}%")
    print("  -> under-converged (needs more iters)" if abs(at8-conv) > 1.0 else "  -> 8 iters OK; inelasticity is real")
