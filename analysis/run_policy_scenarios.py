#!/usr/bin/env python3
"""
run_policy_scenarios.py — sequential runner for Phase 7 policy XMLs.

Reads:  scenarios/maryland/policy/*.xml  (all configs)
Writes: output/policy/<sid>/...           (per-scenario MATSim output dirs)
        output/policy/_runner.log         (runner-level log: start/end/exit codes)

Run order: alphabetical (P1, P2, ..., P6). Each scenario is invoked with the
same JVM flags as the baseline (--add-opens for Guice/cglib, -Xmx24g for safety
on 64 GB hosts).

Idempotency: if output/policy/<sid>/logfile.log exists AND contains
"ITERATION 50 ENDS", the scenario is SKIPPED (already complete). Pass
--force to override.

Usage from UrbanEV-Maryland/ root (after sourcing ../tools/env.sh OR with
JAVA_HOME / PATH already correct):
    python analysis/run_policy_scenarios.py
    python analysis/run_policy_scenarios.py --force
    python analysis/run_policy_scenarios.py --only P3_public_5cent,P4_dcfc_5cent
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
POLICY_DIR = REPO / "scenarios" / "maryland" / "policy"
OUTPUT_ROOT = REPO / "output" / "policy"
JAR = REPO / "target" / "UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
RUNNER_LOG = OUTPUT_ROOT / "_runner.log"

# Inherit JAVA from env; tools/env.sh sets JAVA_HOME, or fall back to the
# portable JDK 17 install.
JAVA_HOME_DEFAULT = REPO.parent / "tools" / "jdk-17.0.19+10"
JAVA = os.environ.get("JAVA_HOME", str(JAVA_HOME_DEFAULT))
JAVA_BIN = Path(JAVA) / "bin" / ("java.exe" if os.name == "nt" else "java")

ADD_OPENS = [
    "--add-opens", "java.base/java.lang=ALL-UNNAMED",
    "--add-opens", "java.base/java.util=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED",
    "--add-opens", "java.base/java.net=ALL-UNNAMED",
    "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED",
]


def log(msg: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    RUNNER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNNER_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def already_done(sid: str) -> bool:
    log_file = OUTPUT_ROOT / sid / "logfile.log"
    if not log_file.exists():
        return False
    try:
        with log_file.open("r", encoding="utf-8", errors="ignore") as f:
            tail = f.readlines()[-200:]
        return any("ITERATION 50 ENDS" in line for line in tail)
    except Exception:
        return False


def run_one(cfg: Path, xmx: str) -> int:
    sid = cfg.stem
    out_dir = OUTPUT_ROOT / sid
    log(f"START {sid}  config={cfg.relative_to(REPO)}  out={out_dir.relative_to(REPO)}")
    t0 = time.time()
    cmd = [str(JAVA_BIN), f"-Xmx{xmx}"] + ADD_OPENS + ["-jar", str(JAR), str(cfg)]
    log_path = OUTPUT_ROOT / f"{sid}.log"
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(cmd, cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT)
    dt = time.time() - t0
    status = "OK" if proc.returncode == 0 else f"FAIL(rc={proc.returncode})"
    log(f"END   {sid}  {status}  elapsed={dt/3600:.2f}h  log={log_path.relative_to(REPO)}")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="Re-run scenarios even if logfile.log shows ITERATION 50 ENDS.")
    ap.add_argument("--only", default="",
                    help="Comma-separated list of scenario IDs to run (default: all).")
    ap.add_argument("--xmx", default="24g",
                    help="JVM max heap (default 24g; 32g if you have plenty of RAM).")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="Abort the sweep on the first non-zero exit code.")
    args = ap.parse_args()

    if not JAR.exists():
        print(f"ERROR: jar not found at {JAR}. Build first: mvn -DskipTests package")
        return 2
    if not JAVA_BIN.exists():
        print(f"ERROR: java not found at {JAVA_BIN}. Set JAVA_HOME or source tools/env.sh")
        return 2
    if not POLICY_DIR.exists():
        print(f"ERROR: policy config dir missing: {POLICY_DIR}")
        return 2

    cfgs = sorted(POLICY_DIR.glob("*.xml"))
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        cfgs = [c for c in cfgs if c.stem in wanted]
    if not cfgs:
        print("ERROR: no policy configs matched.")
        return 2

    log(f"==== POLICY SWEEP START ({len(cfgs)} scenarios) ====")
    log(f"     java  = {JAVA_BIN}")
    log(f"     jar   = {JAR.relative_to(REPO)}")
    log(f"     xmx   = {args.xmx}")
    log(f"     force = {args.force}")

    rcs = []
    for cfg in cfgs:
        sid = cfg.stem
        if not args.force and already_done(sid):
            log(f"SKIP  {sid}  (logfile.log already has ITERATION 50 ENDS; use --force to re-run)")
            rcs.append(0)
            continue
        rc = run_one(cfg, args.xmx)
        rcs.append(rc)
        if rc != 0 and args.stop_on_fail:
            log(f"ABORT after {sid} failed; --stop-on-fail set.")
            break

    n_ok = sum(1 for r in rcs if r == 0)
    log(f"==== POLICY SWEEP DONE  ok={n_ok}/{len(rcs)} ====")
    return 0 if all(r == 0 for r in rcs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
