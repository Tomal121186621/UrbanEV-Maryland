#!/usr/bin/env python3
"""Wait for the 100% per-type baseline to finish, then warm-start all 4 policies from it
(per-type prices + surcharges), 2 concurrent, log-suppressed. Gold-standard consistent set."""
import subprocess, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MD = Path(__file__).resolve().parents[1]              # UrbanEV-Maryland
SC = MD / "scenarios/maryland"; REPO = MD.parent
JAVA = str(REPO / "tools/jdk-17.0.19+10/bin/java")
JAR = str(MD / "target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar")
QUIET = str(SC / "log4j2_quiet.xml")
RUNS = SC / "output/runs_2026"
BASE_PLANS = RUNS / "baseline_pertype/output_plans.xml.gz"
SIDS = ["T1_state_public_5c", "T2_state_public_10c", "T3_utility_evrider_3c", "T4_combined_5c_2c"]
OPENS = ["--add-opens", "java.base/java.lang=ALL-UNNAMED", "--add-opens", "java.base/java.util=ALL-UNNAMED",
         "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED", "--add-opens", "java.base/java.nio=ALL-UNNAMED",
         "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED"]

print("[pertype-policies] waiting for baseline_pertype/output_plans.xml.gz ...", flush=True)
while not BASE_PLANS.exists():
    time.sleep(120)
time.sleep(60)
print("[pertype-policies] baseline done -> launching 4 policies (2 concurrent)", flush=True)


def run(sid):
    cfg = f"config_policy_{sid}_pertype.xml"
    log = f"/tmp/policy_{sid}_pertype.log"
    with open(log, "w") as lf:
        subprocess.run([JAVA, f"-Dlog4j2.configurationFile={QUIET}", *OPENS, "-Xmx30g",
                        "-cp", JAR, "se.umd.MdEVMain", cfg], cwd=str(SC), stdout=lf, stderr=subprocess.STDOUT)
    return sid


with ThreadPoolExecutor(max_workers=2) as ex:
    for sid in ex.map(run, SIDS):
        print(f"[pertype-policies] done: {sid}", flush=True)
print("[pertype-policies] ALL per-type policies complete", flush=True)
