#!/usr/bin/env python3
"""Session-START diurnal validation (the metric where the two-peak structure lives).
Observed starts are derived from ChargePoint occupancy polls: per-station increases in
in_use_ports = new plug-in events (1.76M polls, sub-minute cadence, ET). Simulated starts =
public charging-session start hours from the converged baseline. Both as hour-of-day shares.
-> paper/figures/validation_trb/fig_val_session_starts.png"""
import sys, glob, sqlite3, warnings
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf
import matplotlib.pyplot as plt
warnings.filterwarnings("ignore")

REPO = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
OUT = REPO/"paper/figures/validation_trb"
DB = REPO/"Baseline Validation/Data/ChargePoint Data Collection/chargepoint_md.db"

# ---- observed: plug-in events from poll transitions ----
con = sqlite3.connect(DB)
d = pd.read_sql("SELECT station_id, accessed_time_utc, in_use_ports FROM charging_session_v2", con)
d["t"] = pd.to_datetime(d.accessed_time_utc, utc=True).dt.tz_convert("US/Eastern")
d = d.sort_values(["station_id","t"])
d["delta"] = d.groupby("station_id").in_use_ports.diff()
starts = d[d.delta > 0].copy()
starts["h"] = starts.t.dt.hour
cp = starts.groupby("h").delta.sum()                      # new plug-ins per hour-of-day
cp = (cp/cp.sum()).reindex(range(24), fill_value=0)
print(f"ChargePoint: {int(starts.delta.sum()):,} plug-in events derived from {len(d):,} polls")

# ---- simulated: public session starts (converged baseline) ----
RUNS = REPO/"UrbanEV-Maryland/scenarios/maryland/output/runs_2026"
f = sorted(glob.glob(str(RUNS/"baseline_pertype/ITERS/it.*/*.charging_sessions.csv")),
           key=lambda p:int(p.split("it.")[1].split("/")[0]))[-1]
s = pd.read_csv(f, sep=";")
pub = s[s.charger_type_3way=="public"].copy()
pub["h"] = (pd.to_numeric(pub.time_start_s)//3600 % 24).astype(int)
sim = pub.groupby("h").size(); sim = (sim/sim.sum()).reindex(range(24), fill_value=0)
print(f"simulation: {len(pub):,} public session starts")

r = np.corrcoef(cp.values, sim.values)[0,1]
tvd = 0.5*np.abs(cp.values - sim.values).sum()

fig, ax = pf.newfig(7.4, 4.4)
ax.plot(range(24), cp.values*100, "-o", color=pf.BLUE, ms=5, lw=2, label="ChargePoint plug-in events (observed)")
ax.plot(range(24), sim.values*100, "-s", color=pf.ORANGE, ms=5, lw=2, label="simulated public session starts")
for pk in [cp.idxmax(), sim.idxmax()]:
    pass
ax.set(xlabel="hour of day (ET)", ylabel="share of daily session starts (%)",
       title=f"Public-charging session starts: simulation vs ChargePoint  (r={r:.2f}, TVD={tvd:.3f})",
       xticks=range(0,24,3))
ax.legend(fontsize=9); ax.grid(alpha=0.25)
pf.save(fig, OUT, "fig_val_session_starts")
print(f"r={r:.3f}  TVD={tvd:.3f}  peaks: CP {cp.idxmax()}h & {cp.drop(cp.idxmax()).idxmax()}h | "
      f"sim {sim.idxmax()}h & {sim.drop(sim.idxmax()).idxmax()}h")
print("-> fig_val_session_starts.png")
