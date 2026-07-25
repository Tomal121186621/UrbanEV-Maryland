#!/usr/bin/env python3
"""
sensitivity.py — one-at-a-time sensitivity battery at 25% (paper robustness analysis).

Perturbs each key charging parameter +/- from the baseline, holding all else at default,
and extracts the policy-relevant outcome metrics (charger-type shares, total energy, mean
session energy) from each run's final charging_sessions.csv -> a tornado table.

Each run: own folder output/runs_2026/sens_<tag>_25pct/ with its config copied in.
20 iters, 4 threads, 4 concurrent.
"""
import subprocess, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCEN = ROOT / "scenarios" / "maryland"
BASE = SCEN / "config_25pct_base.xml"
JAVA = REPO / "tools/jdk-17.0.19+10/bin/java"
JAR = ROOT / "target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
OPENS = ["--add-opens", "java.base/java.lang=ALL-UNNAMED", "--add-opens",
         "java.base/java.lang.reflect=ALL-UNNAMED", "--add-opens", "java.base/java.util=ALL-UNNAMED",
         "--add-opens", "java.base/java.nio=ALL-UNNAMED", "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED"]
LAST_ITER = 20; CONC = 4

# (param name in config, low value, high value)  — baseline defaults in comments
PERTURB = [
    ("alphaScaleCost", 0.5, 1.5),            # base 1.0  (cost sensitivity)
    ("defaultRangeAnxietyThreshold", 0.1, 0.3),  # base 0.2 (charge frequency)
    ("socDifferenceUtility", -2, -6),        # base -4   (charge depth)
    ("publicChargingCost", 0.30, 0.50),      # base 0.40 (public price)
]


def make_config(param, val, tag):
    txt = BASE.read_text()
    txt = re.sub(rf'(name="{param}" value=")[^"]*"', rf'\g<1>{val}"', txt)
    txt = re.sub(r'(name="lastIteration" value=")[^"]*"', rf'\g<1>{LAST_ITER}"', txt)
    txt = re.sub(r'(outputDirectory" value=")[^"]*"', rf'\g<1>output/runs_2026/sens_{tag}_25pct"', txt)
    p = SCEN / f"config_sens_{tag}.xml"; p.write_text(txt)
    return p


def run_one(job):
    param, val, tag = job
    make_config(param, val, tag)
    log = SCEN / "output/runs_2026" / f"sens_{tag}_25pct_launch.log"
    with open(log, "w") as lf:
        subprocess.run([str(JAVA), *OPENS, "-Xmx10g", "-jar", str(JAR), f"config_sens_{tag}.xml"],
                       cwd=str(SCEN), stdout=lf, stderr=subprocess.STDOUT)
    out = SCEN / f"output/runs_2026/sens_{tag}_25pct"
    (out).mkdir(exist_ok=True)
    cfg = SCEN / f"config_sens_{tag}.xml"
    if cfg.exists() and out.exists():
        (out / cfg.name).write_bytes(cfg.read_bytes())        # save config in run folder
    sess = out / f"ITERS/it.{LAST_ITER}/{LAST_ITER}.charging_sessions.csv"
    if not sess.exists():
        return dict(param=param, val=val, tag=tag, note="no sessions")
    d = pd.read_csv(sess, sep=";")
    n = len(d); e = pd.to_numeric(d.energy_kwh, errors="coerce")
    sh = d.charger_type_3way.value_counts(normalize=True)
    return dict(param=param, val=val, tag=tag, n=n,
                home=round(sh.get("home", 0), 3), public=round(sh.get("public", 0), 3),
                work=round(sh.get("work", 0), 3),
                tot_MWh=round(e.sum() / 1000, 1), mean_kwh=round(e.mean(), 2))


def main():
    jobs = []
    for param, lo, hi in PERTURB:
        jobs.append((param, lo, f"{param[:8]}_lo"))
        jobs.append((param, hi, f"{param[:8]}_hi"))
    print(f"[sensitivity] {len(jobs)} runs, {CONC} concurrent, {LAST_ITER} iters")
    rows = []
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        for r in ex.map(run_one, jobs):
            rows.append(r); print("  done:", r, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "analysis/sensitivity_results.csv", index=False)
    print("\n=== SENSITIVITY (vs baseline) ===\n", df.to_string(index=False))


if __name__ == "__main__":
    main()
