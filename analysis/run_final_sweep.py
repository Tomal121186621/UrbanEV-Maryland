#!/usr/bin/env python3
"""
run_final_sweep.py — sequential launcher for baseline + S1-S4 policy sweep.

Designed to be started while the final baseline is already running. Polls
for baseline completion (presence of output_config.xml in baseline output dir,
which MATSim only writes on clean shutdown), then launches policy_S1, S2, S3,
S4 sequentially.

Run from repo root (UrbanEV-Maryland/):

    py analysis/run_final_sweep.py                  # wait for baseline then run all 4
    py analysis/run_final_sweep.py --skip-wait      # baseline already done; just run S1-S4
    py analysis/run_final_sweep.py --only S1,S3     # only specific scenarios
    py analysis/run_final_sweep.py --dry-run        # print commands without launching

Per-run logging: output/final_runs/<scenario>_launch.log
Sweep manifest: output/final_runs/sweep_manifest.csv
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
FINAL_DIR = REPO_ROOT / "scenarios" / "maryland" / "final"
OUTPUT_DIR = REPO_ROOT / "output" / "final_runs"
JAR = REPO_ROOT / "target" / "UrbanEV-Maryland-1.0-jar-with-dependencies.jar"
JDK_BIN = PROJECT_ROOT / "tools" / "jdk-17.0.19+10" / "bin"

POLICY_ORDER = ["S1", "S2", "S3", "S4"]

ADD_OPENS = [
    "--add-opens", "java.base/java.lang=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang.reflect=ALL-UNNAMED",
    "--add-opens", "java.base/java.util=ALL-UNNAMED",
    "--add-opens", "java.base/java.nio=ALL-UNNAMED",
    "--add-opens", "java.base/sun.nio.ch=ALL-UNNAMED",
]

BASELINE_DONE_MARKER = OUTPUT_DIR / "baseline" / "output_config.xml"


def find_java() -> Path:
    cand = JDK_BIN / ("java.exe" if os.name == "nt" else "java")
    if not cand.exists():
        raise SystemExit(f"ERROR: portable JDK 17 not found at {cand}")
    return cand


def wait_for_baseline(poll_sec: int = 60) -> None:
    """Block until baseline writes output_config.xml (signal of clean shutdown)."""
    print(f"[sweep] waiting for baseline marker: {BASELINE_DONE_MARKER}")
    print(f"[sweep] polling every {poll_sec}s ...")
    t0 = time.time()
    while not BASELINE_DONE_MARKER.exists():
        elapsed_h = (time.time() - t0) / 3600
        print(f"[sweep] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
              f"baseline still running (waited {elapsed_h:.1f}h)", flush=True)
        time.sleep(poll_sec)
    print(f"[sweep] BASELINE COMPLETE at {datetime.now()}; starting policy sweep")


def run_one(scenario: str, xmx: str, dry: bool) -> dict:
    """Launch one policy scenario JVM, block until exit, return manifest row."""
    cfg = FINAL_DIR / f"policy_{scenario}.xml"
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
        print(f"[sweep] {scenario}: DRY-RUN\n        " + " ".join(cmd))
        row["status"] = "DRY_RUN"
        return row

    print(f"[sweep] {scenario}: START  cfg={cfg.name}  log={log_path.name}")
    t0 = time.time()
    with log_path.open("w", encoding="utf-8") as logf:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), stdout=logf,
                              stderr=subprocess.STDOUT, text=True)
    elapsed = time.time() - t0

    row["end_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row["elapsed_s"] = int(elapsed)
    row["exit_code"] = proc.returncode
    row["status"] = "OK" if proc.returncode == 0 else f"FAIL(exit={proc.returncode})"
    print(f"[sweep] {scenario}: DONE  exit={proc.returncode}  "
          f"elapsed={elapsed/3600:.2f}h  status={row['status']}")
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
    print(f"[sweep] manifest -> {out.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(POLICY_ORDER),
                    help="comma-list of scenarios (default: all 4)")
    ap.add_argument("--xmx", default="32g", help="JVM heap (default 32g)")
    ap.add_argument("--skip-wait", action="store_true",
                    help="don't wait for baseline; start S1 immediately")
    ap.add_argument("--poll-sec", type=int, default=60,
                    help="baseline poll interval (default 60s)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    scenarios = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in POLICY_ORDER]
    if unknown:
        raise SystemExit(f"unknown scenarios: {unknown}; valid: {POLICY_ORDER}")

    if not args.skip_wait and not args.dry_run:
        wait_for_baseline(poll_sec=args.poll_sec)
    elif args.skip_wait:
        print(f"[sweep] --skip-wait: not waiting for baseline marker")

    rows = []
    for s in scenarios:
        rows.append(run_one(s, args.xmx, args.dry_run))
        write_manifest(rows)  # write after each so partial progress is captured

    failed = [r for r in rows if r["status"] not in ("OK", "DRY_RUN")]
    if failed:
        print(f"[sweep] FAILURES: {[r['scenario'] for r in failed]}")
        return 2
    print(f"[sweep] all {len(rows)} scenarios complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
