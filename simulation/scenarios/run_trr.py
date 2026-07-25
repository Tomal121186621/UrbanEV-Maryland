#!/usr/bin/env python3
"""TRR campaign: 11 runs (9 UQ seed replicates + 2 price sensitivities), 4 concurrent,
idempotent. Per TRR_Run_Plan.pdf; -Xmx20g (empirically sufficient for 25% runs)."""
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
SC = Path(__file__).resolve().parent; MD = SC.parents[1]; REPO = MD.parent
JAVA = str(REPO/"tools/jdk-17.0.19+10/bin/java")
JAR = str(MD/"target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar")
QUIET = str(SC/"log4j2_quiet.xml")
OPENS = ["--add-opens","java.base/java.lang=ALL-UNNAMED","--add-opens","java.base/java.util=ALL-UNNAMED",
         "--add-opens","java.base/java.lang.reflect=ALL-UNNAMED","--add-opens","java.base/java.nio=ALL-UNNAMED",
         "--add-opens","java.base/sun.nio.ch=ALL-UNNAMED"]
NAMES = [l.strip() for l in (SC/"trr_manifest.txt").read_text().splitlines() if l.strip()]
import re
def outdir(name):
    cfg=(SC/f"config_{name}.xml").read_text()
    return SC/re.search(r'"outputDirectory" value="([^"]+)"',cfg).group(1)
def run(name):
    od = outdir(name)
    if (od/"output_plans.xml.gz").exists():
        print(f"[skip] {name}", flush=True); return
    print(f"[start] {name}", flush=True)
    with open(SC/f"output/runs_trr/{name}_launch.log","w") as lf:
        subprocess.run([JAVA, f"-Dlog4j2.configurationFile={QUIET}", *OPENS, "-Xmx20g",
                        "-cp", JAR, "se.umd.MdEVMain", f"config_{name}.xml"],
                       cwd=str(SC), stdout=lf, stderr=subprocess.STDOUT)
    print(f"[{'done' if (od/'output_plans.xml.gz').exists() else 'FAIL'}] {name}", flush=True)
print(f"[trr] {len(NAMES)} runs, 4 concurrent", flush=True)
with ThreadPoolExecutor(max_workers=4) as ex:
    list(ex.map(run, NAMES))
print("[trr] ALL COMPLETE", flush=True)
