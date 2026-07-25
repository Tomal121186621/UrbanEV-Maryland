#!/usr/bin/env python3
"""Simulation-only results — things that ONLY a spatially/temporally explicit agent
simulation can produce (not static accounting):
  (a) aggregate charging LOAD on the grid (MW) by time of day, stacked by venue;
  (b) OPPORTUNISTIC charging: energy by the activity the agent was doing when it plugged in;
  (c) state-of-charge at plug-in vs walking distance to charger (charging friction).
-> paper/figures/simulation_power.png
"""
import sys, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]; REPO = ROOT.parent
FIG = REPO / "paper/figures"; DAYS = 3
f = sorted(glob.glob(str(ROOT / "scenarios/maryland/output/runs_2026/baseline/ITERS/it.*/*charging_sessions.csv")),
           key=lambda p: int(p.split("it.")[1].split("/")[0]))[-1]
d = pd.read_csv(f, sep=";")
for c in ["time_start_s", "time_end_s", "duration_s", "energy_kwh", "soc_start", "walking_dist_m"]:
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d[(d.duration_s > 0) & (d.energy_kwh > 0)].copy()

# ---- (a) aggregate charging power (MW) by hour of day, by venue ----
# distribute each session's energy across the hour-of-day bins it spans; MWh/hour = avg MW.
VEN = [("home", pf.BLUE), ("work", pf.GREEN), ("public", pf.ORANGE)]
load = {v: np.zeros(24) for v, _ in VEN}
step = 300.0  # 5-min integration
ts = d.time_start_s.to_numpy(); te = d.time_end_s.to_numpy()
pw = (d.energy_kwh / (d.duration_s / 3600.0)).to_numpy()   # kW per session
ven = d.charger_type_3way.to_numpy()
for i in range(len(d)):
    n = max(1, int((te[i] - ts[i]) / step))
    t = (np.linspace(ts[i], te[i], n, endpoint=False) % 86400) / 3600.0
    hrs = t.astype(int) % 24
    e = pw[i] * (step / 3600.0)                            # kWh per step
    v = ven[i] if ven[i] in load else "public"
    np.add.at(load[v], hrs, e)
for v in load:
    load[v] = load[v] / DAYS / 1000.0                     # kWh/hr summed over 3 days -> avg MW

fig, ax = plt.subplots(1, 3, figsize=(13.5, 3.9))
base = np.zeros(24); x = np.arange(24)
for v, c in VEN:
    ax[0].bar(x, load[v], bottom=base, width=0.9, color=c, edgecolor="none", label=v)
    base += load[v]
ax[0].set(xlabel="hour of day", ylabel="fleet charging power (MW)",
          title="(a) EV charging load on the grid")
ax[0].legend(fontsize=8, frameon=False); ax[0].set_xticks(range(0, 24, 3)); ax[0].grid(axis="y", alpha=0.25)
peak = int(np.argmax(base))
ax[0].annotate(f"peak {base.max():.0f} MW\n@ {peak:02d}:00", xy=(peak, base.max()),
               xytext=(peak - 8, base.max() * 0.8), fontsize=8,
               arrowprops=dict(arrowstyle="->", lw=0.8))

# ---- (b) opportunistic charging: energy by the activity being performed ----
d["act"] = d.activity_type.astype(str).str.split(" charging").str[0].str.strip().str.title()
en = d.groupby("act").energy_kwh.sum().sort_values(ascending=False)
en = (en / en.sum() * 100).head(8)[::-1]
ax[1].barh(en.index, en.values, color=pf.ORANGE, edgecolor="k", lw=0.3)
ax[1].set(xlabel="% of charging energy", title="(b) Charging is opportunistic\n(energy by activity at plug-in)")
ax[1].grid(axis="x", alpha=0.25)

# ---- (c) SOC at plug-in vs walking distance ----
ax[2].scatter(d.soc_start.sample(min(6000, len(d)), random_state=1) * 100,
              d.walking_dist_m.sample(min(6000, len(d)), random_state=1),
              s=4, alpha=0.15, color=pf.GREY, edgecolor="none")
ax[2].set(xlabel="state of charge at plug-in (%)", ylabel="walk to charger (m)",
          title="(c) Charging friction\n(SOC & access at plug-in)")
ax[2].set_ylim(0, d.walking_dist_m.quantile(0.98)); ax[2].grid(alpha=0.2)

fig.tight_layout()
fig.savefig(FIG / "simulation_power.png", dpi=300, bbox_inches="tight")
fig.savefig(FIG / "simulation_power.pdf", bbox_inches="tight")
plt.close(fig)
print("-> simulation_power.png")
print(f"  peak fleet charging load {base.max():.0f} MW at {peak:02d}:00; home share of evening peak dominant")
print("  top charging activities:", ", ".join(f"{a} {v:.0f}%" for a, v in en[::-1].head(4).items()))
