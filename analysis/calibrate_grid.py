#!/usr/bin/env python3
"""
calibrate_grid.py — 25% charging-model calibration grid, 4 runs concurrent.

Grid over the two most impactful params (rangeAnxietyUtility fixed at the -6 default;
refined afterward if needed):
    alphaScaleCost       in {0.6, 1.0, 1.6}   (global x per-agent betaMoney; cost sens.)
    socDifferenceUtility in {-2, -4, -7}       (charge depth -> session energy)
Center (1.0, -4) == cal_baseline (already running), so only the other 8 are launched here.
Each 25% run: 20 iterations, 4 threads, ~7 h; 4 concurrent -> ~2 batches.
Scores each run's it.20 charging_sessions.csv against EV-WATTS (evwatts_targets.py) and
writes a ranked calibrate_grid_results.csv.
"""
import subprocess, itertools, re, time, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]                     # UrbanEV-Maryland
REPO = ROOT.parent
SCEN = ROOT / "scenarios" / "maryland"
BASE = SCEN / "config_25pct_base.xml"
JAVA = REPO / "tools/jdk-17.0.19+10/bin/java"
JAR = ROOT / "target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
OPENS = ["--add-opens", "java.base/java.lang=ALL-UNNAMED",
         "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED",
         "--add-opens", "java.base/java.util=ALL-UNNAMED",
         "--add-opens", "java.base/java.nio=ALL-UNNAMED",
         "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED"]
ALPHA = [0.6, 1.0, 1.6]
SOC = [-2, -4, -7]
RANX = -6
LAST_ITER = 20
CONC = 3

sys.path.insert(0, str(ROOT / "analysis"))
import evwatts_targets as ew


def make_config(a, s, tag):
    txt = BASE.read_text()
    txt = re.sub(r'(name="alphaScaleCost" value=")[^"]*"', rf'\g<1>{a}"', txt)
    txt = re.sub(r'(name="socDifferenceUtility" value=")[^"]*"', rf'\g<1>{s}"', txt)
    txt = re.sub(r'(name="rangeAnxietyUtility" value=")[^"]*"', rf'\g<1>{RANX}"', txt)
    txt = re.sub(r'(name="lastIteration" value=")[^"]*"', rf'\g<1>{LAST_ITER}"', txt)
    txt = re.sub(r'(outputDirectory" value=")[^"]*"', rf'\g<1>output/runs_2026/cal_{tag}"', txt)
    p = SCEN / f"config_cal_{tag}.xml"; p.write_text(txt); return p


def run_one(cell):
    a, s = cell; tag = f"a{a}_s{s}".replace(".", "").replace("-", "m")
    cfg = make_config(a, s, tag)
    log = SCEN / "output/runs_2026" / f"cal_{tag}_launch.log"
    with open(log, "w") as lf:
        subprocess.run([str(JAVA), *OPENS, "-Xmx10g", "-jar", str(JAR),
                        f"config_cal_{tag}.xml"], cwd=str(SCEN), stdout=lf, stderr=subprocess.STDOUT)
    sess = SCEN / f"output/runs_2026/cal_{tag}/ITERS/it.{LAST_ITER}/{LAST_ITER}.charging_sessions.csv"
    if not sess.exists():
        return dict(alpha=a, soc=s, tag=tag, score=None, note="no sessions")
    tot, parts, n = ew.score(sess)
    return dict(alpha=a, soc=s, tag=tag, score=round(tot, 4), n=n, **{k: round(v, 3) for k, v in parts.items()})


def main():
    cells = [c for c in itertools.product(ALPHA, SOC) if c != (1.0, -4)]   # center = cal_baseline
    print(f"[grid] {len(cells)} runs, {CONC} concurrent, {LAST_ITER} iters each")
    rows = []
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        for r in ex.map(run_one, cells):
            rows.append(r); print("  done:", r, flush=True)
    # add center once it exists
    import pandas as pd
    df = pd.DataFrame(rows).sort_values("score", na_position="last")
    df.to_csv(ROOT / "analysis/calibrate_grid_results.csv", index=False)
    print("\n=== RANKED (lower TVD = better) ===")
    print(df.to_string(index=False))
    print("\nbest:", df.iloc[0].to_dict())


if __name__ == "__main__":
    main()
