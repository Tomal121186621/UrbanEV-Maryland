#!/usr/bin/env python3
"""Run the CONVERGED policy sweep: 12 scenarios at 25% sample, 50 iterations, warm-started
from seed_1001_25pct. 4 concurrent, idempotent, log-suppressed. Produces the correct
(fully-converged) Laffer / elasticity / T1-T4 numbers to replace the under-converged 8-iter runs.
Baseline (cv equivalent) = diag_base_25pct; pub_150c = diag_pub150_25pct (both already done)."""
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SC = Path(__file__).resolve().parent; MD = SC.parents[1]; REPO = MD.parent
JAVA = str(REPO/"tools/jdk-17.0.19+10/bin/java")
JAR = str(MD/"target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar")
QUIET = str(SC/"log4j2_quiet.xml")
RUNS = SC/"output/runs_2026/converged"; RUNS.mkdir(parents=True, exist_ok=True)
OPENS = ["--add-opens","java.base/java.lang=ALL-UNNAMED","--add-opens","java.base/java.util=ALL-UNNAMED",
         "--add-opens","java.base/java.lang.reflect=ALL-UNNAMED","--add-opens","java.base/java.nio=ALL-UNNAMED",
         "--add-opens","java.base/sun.nio.ch=ALL-UNNAMED"]
NAMES = [l.strip() for l in (SC/"converged_manifest.txt").read_text().splitlines() if l.strip()]

def run(name):
    od = RUNS/name
    if (od/"output_plans.xml.gz").exists():
        print(f"[skip] {name}", flush=True); return name
    print(f"[start] {name}", flush=True)
    with open(RUNS/f"{name}_launch.log", "w") as lf:
        subprocess.run([JAVA, f"-Dlog4j2.configurationFile={QUIET}", *OPENS, "-Xmx20g",
                        "-cp", JAR, "se.umd.MdEVMain", f"config_{name}.xml"],
                       cwd=str(SC), stdout=lf, stderr=subprocess.STDOUT)
    print(f"[{'done' if (od/'output_plans.xml.gz').exists() else 'FAIL'}] {name}", flush=True)
    return name

print(f"[converged] {len(NAMES)} scenarios, 4 concurrent, 25% / 50 iters", flush=True)
with ThreadPoolExecutor(max_workers=4) as ex:
    list(ex.map(run, NAMES))
print("[converged] ALL COMPLETE", flush=True)
