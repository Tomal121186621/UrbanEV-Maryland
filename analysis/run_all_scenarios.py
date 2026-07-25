#!/usr/bin/env python3
"""Unified scenario runner: 4 per-type policies (T1-T4) + 9 price-sweep scenarios, all
warm-started from baseline_pertype, 8 iters each, 3 concurrent (~90 GB, no thrashing).
Policies run first (paper's core table); idempotent (skips any with output_plans already)."""
import re, subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MD = Path(__file__).resolve().parents[1]                 # UrbanEV-Maryland
SC = MD / "scenarios/maryland"; REPO = MD.parent
JAVA = str(REPO / "tools/jdk-17.0.19+10/bin/java")
JAR = str(MD / "target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar")
QUIET = str(SC / "log4j2_quiet.xml")
RUNS = SC / "output/runs_2026"
BASE_PLANS = RUNS / "baseline_pertype/output_plans.xml.gz"
OPENS = ["--add-opens", "java.base/java.lang=ALL-UNNAMED", "--add-opens", "java.base/java.util=ALL-UNNAMED",
         "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED", "--add-opens", "java.base/java.nio=ALL-UNNAMED",
         "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED"]

CONFIGS = [                                               # policies FIRST (paper priority)
    "config_policy_T1_state_public_5c_pertype.xml",
    "config_policy_T2_state_public_10c_pertype.xml",
    "config_policy_T3_utility_evrider_3c_pertype.xml",
    "config_policy_T4_combined_5c_2c_pertype.xml",
    "config_sweep_pub_10c.xml", "config_sweep_pub_25c.xml", "config_sweep_pub_50c.xml",
    "config_sweep_pub_100c.xml", "config_sweep_pub_150c.xml", "config_sweep_pub_200c.xml",
    "config_sweep_home_10c.xml", "config_sweep_home_22c.xml", "config_sweep_home_40c.xml",
]


def outdir(cfg):
    m = re.search(r'name="outputDirectory" value="([^"]+)"', (SC / cfg).read_text())
    return SC / m.group(1)


def run(cfg):
    od = outdir(cfg)
    if (od / "output_plans.xml.gz").exists():
        print(f"[skip] {cfg} (already complete)", flush=True); return cfg
    print(f"[start] {cfg} -> {od.name}", flush=True)
    with open(RUNS / f"{od.name}_launch.log", "w") as lf:
        subprocess.run([JAVA, f"-Dlog4j2.configurationFile={QUIET}", *OPENS, "-Xmx30g",
                        "-cp", JAR, "se.umd.MdEVMain", cfg], cwd=str(SC), stdout=lf, stderr=subprocess.STDOUT)
    ok = (od / "output_plans.xml.gz").exists()
    print(f"[{'done' if ok else 'FAILED'}] {cfg}", flush=True)
    return cfg


print(f"[unified] {len(CONFIGS)} scenarios, 3 concurrent, 8 iters each", flush=True)
while not BASE_PLANS.exists():
    time.sleep(120)
with ThreadPoolExecutor(max_workers=3) as ex:
    for _ in ex.map(run, CONFIGS):
        pass
print("[unified] ALL SCENARIOS COMPLETE", flush=True)
