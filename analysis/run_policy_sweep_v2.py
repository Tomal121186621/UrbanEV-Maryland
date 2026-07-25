#!/usr/bin/env python3
"""
run_policy_sweep_v2.py - sequential launcher for the P1/P2/P3 policy sweep.

Runs precedent-anchored, goal-sized policy scenarios:
  P1 - Universal +$0.14/kWh state EV fee (Iowa/OK precedent)
  P2 - VMT-equivalent road-use charge (Oregon OReGO precedent)
  P3 - Utility EV-rider tariff (BGE/Pepco precedent)

Each warm-starts from output/final_runs/baseline/output_plans.xml.gz and runs
20 iterations (16 innovating + 4 frozen) at 100% MD scale.

Outputs land in output/policy_sweep_v2/policy_P{1,2,3}/ (clean folder, separate
from the abandoned S1-S4 sweep in output/final_runs/).

Run from repo root (UrbanEV-Maryland/):

    py analysis/run_policy_sweep_v2.py                  # all 3, sequential
    py analysis/run_policy_sweep_v2.py --only P1        # one scenario
    py analysis/run_policy_sweep_v2.py --dry-run        # print commands only

Per-run logging: output/policy_sweep_v2/policy_<P>_launch.log
Sweep manifest:  output/policy_sweep_v2/sweep_manifest.csv
"""
from __future__ import annotations
import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = REPO_ROOT.parent
CFG_DIR = REPO_ROOT / "scenarios" / "maryland" / "policy_v2"
OUTPUT_DIR = REPO_ROOT / "output" / "policy_sweep_v2"
JAR = REPO_ROOT / "target" / "UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
JDK_BIN = PROJECT_ROOT / "tools" / "jdk-17.0.19+10" / "bin"

POLICY_ORDER = ["P1", "P2", "P3", "P5", "P6"]

ADD_OPENS = [
    "--add-opens", "java.base/java.lang=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED",
    "--add-opens", "java.base/java.util=ALL-UNNAMED",
    "--add-opens", "java.base/java.nio=ALL-UNNAMED",
    "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED",
]


def find_java() -> Path:
    cand = JDK_BIN / ("java.exe" if os.name == "nt" else "java")
    if not cand.exists():
        raise SystemExit(f"ERROR: portable JDK 17 not found at {cand}")
    return cand


def run_one(scenario: str, xmx: str, dry: bool) -> dict:
    cfg = CFG_DIR / f"policy_{scenario}.xml"
    out_dir = OUTPUT_DIR / f"policy_{scenario}"
    log_path = OUTPUT_DIR / f"policy_{scenario}_launch.log"
    if not cfg.exists():
        raise FileNotFoundError(f"missing config: {cfg}")

    java = find_java()
    cmd = [str(java), f"-Xmx{xmx}", *ADD_OPENS, "-jar", str(JAR),
           str(cfg.relative_to(REPO_ROOT))]

    row = {
        "scenario": scenario,
        "config": cfg.name,
        "outdir": out_dir.relative_to(REPO_ROOT).as_posix(),
        "start_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "end_utc": "", "elapsed_s": 0, "exit_code": -1, "status": "PENDING",
    }

    if dry:
        print(f"[sweep_v2] {scenario}: DRY-RUN\n           " + " ".join(cmd))
        row["status"] = "DRY_RUN"
        return row

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[sweep_v2] {scenario}: START  cfg={cfg.name}  log={log_path.name}", flush=True)
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), stdout=logf,
                              stderr=subprocess.STDOUT, text=True)
    elapsed = time.time() - t0

    row["end_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["elapsed_s"] = int(elapsed)
    row["exit_code"] = proc.returncode
    row["status"] = "OK" if proc.returncode == 0 else f"FAIL(exit={proc.returncode})"
    print(f"[sweep_v2] {scenario}: DONE  exit={proc.returncode}  "
          f"elapsed={elapsed/3600:.2f}h  status={row['status']}", flush=True)
    return row


def write_manifest(rows: list[dict]) -> None:
    out = OUTPUT_DIR / "sweep_manifest.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["scenario", "config", "outdir", "start_utc", "end_utc",
            "elapsed_s", "exit_code", "status"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"[sweep_v2] manifest -> {out.relative_to(REPO_ROOT)}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(POLICY_ORDER),
                    help="comma-list of scenarios (default: P1,P2,P3)")
    ap.add_argument("--xmx", default="32g", help="JVM heap (default 32g)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in POLICY_ORDER]
    if unknown:
        raise SystemExit(f"unknown scenarios: {unknown}; valid: {POLICY_ORDER}")

    rows = []
    for s in scenarios:
        rows.append(run_one(s, args.xmx, args.dry_run))
        write_manifest(rows)

    failed = [r for r in rows if r["status"] not in ("OK", "DRY_RUN")]
    if failed:
        print(f"[sweep_v2] FAILURES: {[r['scenario'] for r in failed]}")
        return 2
    print(f"[sweep_v2] all {len(rows)} scenarios complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
