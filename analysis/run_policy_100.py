#!/usr/bin/env python3
"""
run_policy_100.py — auto-fire the 100% warm-started policy sweep once the baseline finishes.

Waits for output/runs_2026/baseline/output_plans.xml.gz (written at baseline shutdown),
then runs config_policy_*.xml (3 concurrent, RAM-safe at 100%), copies each config +
RUN_INFO into its run folder, and extracts charger-type shares + total energy per scenario.
"""
import subprocess, time, re, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCEN = ROOT / "scenarios" / "maryland"
JAVA = REPO / "tools/jdk-17.0.19+10/bin/java"
JAR = ROOT / "target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
WARM = SCEN / "output/runs_2026/baseline/output_plans.xml.gz"
OPENS = ["--add-opens", "java.base/java.lang=ALL-UNNAMED", "--add-opens",
         "java.base/java.lang.reflect=ALL-UNNAMED", "--add-opens", "java.base/java.util=ALL-UNNAMED",
         "--add-opens", "java.base/java.nio=ALL-UNNAMED", "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED"]
CONC = 4; ITER = 15


def run_one(cfg):
    sid = re.match(r"config_policy_(.+)\.xml", cfg.name).group(1)
    log = SCEN / "output/runs_2026" / f"policy_{sid}_100pct_launch.log"
    with open(log, "w") as lf:
        subprocess.run([str(JAVA), *OPENS, "-Xmx26g", "-jar", str(JAR), cfg.name],
                       cwd=str(SCEN), stdout=lf, stderr=subprocess.STDOUT)
    out = SCEN / f"output/runs_2026/policy_{sid}_100pct"
    if out.exists():
        (out / cfg.name).write_bytes(cfg.read_bytes())
    sess = out / f"ITERS/it.{ITER}/{ITER}.charging_sessions.csv"
    if not sess.exists():
        return dict(scenario=sid, note="no sessions")
    d = pd.read_csv(sess, sep=";"); e = pd.to_numeric(d.energy_kwh, errors="coerce")
    sh = d.charger_type_3way.value_counts(normalize=True)
    return dict(scenario=sid, n=len(d), home=round(sh.get("home", 0), 3),
                public=round(sh.get("public", 0), 3), work=round(sh.get("work", 0), 3),
                tot_MWh=round(e.sum() / 1000, 1))


def main():
    print("[policy] waiting for baseline to finish (output_plans.xml.gz) ...", flush=True)
    while not WARM.exists():
        time.sleep(300)
    time.sleep(120)                                    # let file settle
    cfgs = sorted(SCEN.glob("config_policy_*.xml"))
    print(f"[policy] baseline done -> launching {len(cfgs)} scenarios, {CONC} concurrent", flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=CONC) as ex:
        for r in ex.map(run_one, cfgs):
            rows.append(r); print("  done:", r, flush=True)
    pd.DataFrame(rows).to_csv(ROOT / "analysis/policy_sweep_results.csv", index=False)
    print("\n=== POLICY SWEEP (100%) ===")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
