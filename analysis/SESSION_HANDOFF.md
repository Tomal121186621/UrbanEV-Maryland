# Session handoff — UrbanEV Maryland

Date authored: 2026-06-11
Use this if starting a new Claude Code session so the next agent can resume
without re-deriving context.

---

## 1. Where we are right now (snapshot)

**Prod baseline (100 % MD): RUNNING.**

- Config: `scenarios/maryland/config_prod_100pct.xml`
- Output: `output/prod_100pct/`
- Last seen iteration: **~31** of `lastIteration=100`.
- Convergence: avg EXECUTED score climbing slowly from −33.23 at it.31
  (delta ≈ +0.23/iter and shrinking). Likely converged enough.
- Decision: **stop at iter 50** (~ 2026-06-12 EDT) rather than running the
  full 100 iter. All future runs use `lastIteration=60` w/
  `fractionOfIterationsToDisableInnovation=0.75` (innovation off at 45,
  lock-in 45-60).
- JVM stable (~50 GB RAM, 0 OOM/CME/StackOverflow, SmartChargingEngine
  fired 383 k events; ChargerRemove race fix holding).
- Modal split at it.31: home 66.24 %, work 14.49 %, L2 18.43 %,
  DCFC 0.74 %, TESLA 0.10 %.
- Known calibration issue: `parkingSearchRadius=500 m` produces an 80 %
  L2 attempt-fail rate (2.09 M "No charger found" ERROR logs). This is
  parameter, not code; it is the dominant lever in the upcoming OAT
  sensitivity sweep.
- Known cosmetic bug: `walkingDistance=0.0` in 99.94 % of session CSVs —
  CSV writer bug, behaviour is fine (deferred, not blocking).

## 2. What just changed in this session (so far)

### 2.1 Sub-sampling methodology rewrite (DONE)

- `analysis/subsampling_research.md` — methodology research artifact:
  derived that the previous calib 10 % tier had **9× lower charger
  density per km²** vs prod, causing ~12 pp upward home-share bias.
  Recommended **hybrid α=0.5** scaling: keep `s^α` of stations, scale
  surviving plug_counts by `s^(1-α)`. With s=0.10, α=0.5 → both equal
  `sqrt(s) ≈ 0.316`. `plugCount` is the contention gate in
  `VehicleChargingHandler.java:499` (verified empirically).
- `analysis/subsampling_methodology.md` — operator-facing summary
  (already in repo; the rationale + reproducer + acceptance window).
- `scripts/subsample_chargers.py` — patched with:
  - `--mode hybrid|station_only|plug_only`
  - `--alpha` (default 0.5)
  - Stage-2 thinning: scaled plug-count rounds to 0 → drop station.
    This makes E[total_plugs] = sample × original *exactly*.
  - Extended manifest: `mode`, `alpha`, `p_station`, `p_plug`,
    `plug_capacity{kept_to_ideal_ratio, ratio_status}`,
    `plug_count_distortion_per_type`,
    `station_density_per_cell_delta`.
  - Acceptance window: aggregate plug ratio in [0.85, 1.15] →
    "OK"; outside → "WARN" and review.
- `scripts/subsample_population.py` — patched to emit manifest
  mirroring chargers manifest layout. New fields:
  `stratum_rel_deviation`, `by_evType`, `by_income_decile`,
  `totals.kept_to_ideal_ratio`.

### 2.2 Regenerated calib-tier inputs (DONE)

```
Input/chargers/chargers_10pct.xml          (408 stations, 562 plugs)
Input/chargers/chargers_10pct_manifest.json
Input/population/plans_md_ev_10pct.xml.gz  (9 915 persons, deterministic seed 4711)
Input/population/plans_md_ev_10pct_manifest.json
Input/vehicles/electric_vehicles_clean_10pct.xml  (9 915 vehicles)
```

Key acceptance numbers (verify before using):
- chargers: kept_to_ideal_ratio = **1.059** (OK)
- chargers: L2 distortion **+3.9 %**, DCFC +20.3 %, DCFC_TESLA −4.8 %,
  L1 verbatim
- chargers: 408 stations (vs old strict 11 % scheme's 194 → 2.1× more
  spatial coverage)
- population: kept_to_ideal_ratio = **1.0002** (essentially exact)
- population: by_evType BEV 7 318 / PHEV 2 597 (matches 73.8 %/26.2 %
  national split)

## 3. What is next (do these in order)

### Step A — Sensitivity sweep design (TASK #23-#28)

Per `analysis/sensitivity_design.md` we have 1 center + 12 perturbed
cells = 13 configs. Each runs the new chargers_10pct.xml + 10pct
plans/vehicles. Tier expectations:

| tier | cells | wall/cell | total |
|---|---|---|---|
| 10 % calib | 13 | ~3.5 h | ~46 h (single GPU/CPU, no parallelism) |

1. **Generate 13 configs**: copy `config_calib_10pct.xml` to
   `scenarios/maryland/sensitivity/C{00..12}_*.xml`. Each modifies:
   - `controler.outputDirectory` → `output/sensitivity/C{NN}_<label>`
   - `controler.lastIteration` → `60`
   - `strategy.fractionOfIterationsToDisableInnovation` → `0.75`
   - One perturbed parameter per cell (see `sensitivity_design.md`).
2. **Write `analysis/sensitivity_runner.py`** — driver that launches
   each config sequentially (or 2-wide if memory allows), handles
   logging, and writes a run-manifest CSV.
3. **Write `analysis/sensitivity_extract.py`** — reads each
   `outputDirectory/it.{last}/`, pulls modal split + total energy +
   peak-hour load + agent-disutility totals into a single
   `sensitivity_results.csv`.
4. **Write `analysis/sensitivity_tornado.py`** — tornado plot of
   |Δ outcome / Δ parameter| per cell, sorted. Outputs PDF.
5. **Run C0 sanity cell first** (just the center, no perturbation) to
   verify the new chargers_10pct.xml closes the home-share gap vs
   prod baseline (expect drop from ~12 pp → 3-5 pp). **Gate**: only
   launch the remaining 12 cells if C0 looks reasonable.
6. **Launch full 12-cell sweep** (gated on C0).

### Step B — Re-run baseline at iter=50 (TASK upcoming)

After sensitivity is complete (or in parallel if 2nd machine
available):
- Stop current prod_100pct at iter 50.
- Re-launch `prod_100pct_v2` with `lastIteration=50`,
  `fractionOfIterationsToDisableInnovation=0.75` for the publication
  baseline. (Existing baseline at iter ~50 may suffice — make a
  judgment call once iter 50 is reached.)
- Re-launch sibling scenarios (TOU/pricing variants per Phase 7) all
  at iter=50.

### Step C — Validation (TASK #27 + Phase 6)

- Run `analysis/validate_vs_chargepoint.py output/<run> chargepoint_md.db`
- Run `analysis/validate_vs_evwatts.py output/<run> evwatts.public/`
- §5.4 validation gate: C0 home-share should be within 5 pp of prod
  baseline at the same iter.

### Step D — Defer / drop

- `walkingDistance` CSV writer bug: cosmetic, deferred. Not blocking
  publication unless reviewers ask about walk-leg distance specifically.

## 4. Critical files to read before resuming

| file | why |
|---|---|
| `analysis/subsampling_research.md` | derivation of the α=0.5 hybrid scheme |
| `analysis/subsampling_methodology.md` | operator reference for sub-sampling |
| `analysis/sensitivity_design.md` | 13-cell OAT cell list + Δ-reporting rationale |
| `scripts/subsample_chargers.py` | patched implementation |
| `scripts/subsample_population.py` | patched + manifest |
| `scenarios/maryland/config_calib_10pct.xml` | template for the 13 sensitivity configs |
| `scenarios/maryland/config_prod_100pct.xml` | current running baseline |
| `output/prod_100pct/scorestats.txt` | check current iteration status |
| `Input/chargers/chargers_10pct_manifest.json` | proof of new sub-sample provenance |
| `Input/population/plans_md_ev_10pct_manifest.json` | proof of new pop sub-sample provenance |
| `~/.claude/projects/.../memory/MEMORY.md` | persistent feedback + project context |

## 5. Open task IDs (TaskList)

- #18 [in_progress] Wire sim↔CP crosswalk into loss + launch calib sanity smoke
- #20 [completed] Patch subsample_chargers.py with hybrid α=0.5 scaling
- #21 [completed] Add manifest emission to subsample_population.py
- #22 [completed] Regenerate chargers_10pct.xml with hybrid scheme
- #23 [completed] Generate 13 sensitivity configs (scripts/gen_sensitivity_configs.py)
- #24 [completed] Write analysis/sensitivity_runner.py
- #25 [completed] Write analysis/sensitivity_extract.py
- #26 [completed] Write analysis/sensitivity_tornado.py (smoke-tested with synthetic data)
- #27 [pending] Run C0 sanity check + validation vs prod baseline (NEXT — needs user OK)
- #28 [pending] Launch full 12-cell sensitivity sweep (gated on #27)
- Also pending: stop + (maybe) re-launch prod baseline at iter 50

## 5b. Prod baseline reference numbers (it.31 snapshot)

These are the values C0 must approximately reproduce (within 5 pp on
home%) for the validation gate to pass:

| metric | prod_100pct @ it.31 |
|---|---|
| total_sessions | 136,037 |
| pct_home | **67.58 %** |
| pct_work | 15.15 % |
| pct_L2 | 16.81 % |
| pct_DCFC | 0.44 % |
| pct_DCFC_TESLA | 0.03 % |
| pct_L2_fail (sessions tagged "L2 failed") | 9.09 % |
| revenue_proxy_USD | $461,438 |
| mean_executed_score | -33.229 |

Extracted via `py analysis/sensitivity_extract.py` (parse_sessions
function applied to prod output directly as a sanity test on 2026-06-11).

## 6. Quick-resume commands

```bash
# Verify hybrid sub-sample reproducibility
cd UrbanEV-Maryland
py scripts/subsample_chargers.py --sample 0.10 --alpha 0.5 --seed 4711 --mode hybrid
py scripts/subsample_population.py --sample 0.10 --seed 4711 \
    --plans-out ../Input/population/plans_md_ev_10pct.xml.gz \
    --evs-out ../Input/vehicles/electric_vehicles_clean_10pct.xml

# Check prod baseline progress
tail -1 output/prod_100pct/scorestats.txt
ls output/prod_100pct/ITERS/ | tail -5

# Next action (after handoff): generate sensitivity configs
ls scenarios/maryland/sensitivity/   # should be empty currently
```

## 7. Gotchas to remember

- **JDK 17 required**, not Java 24. Always `source tools/env.sh` first to
  get the `--add-opens` flags for Guice cglib (see memory:
  `project_jvm_run_flags.md`).
- **Charger XML CRS mislabel**: chargers.xml + network are EPSG:**26985**
  (MD State Plane m), not EPSG:26918 as config claims (see memory:
  `project_crs_mislabel.md`). The 50 km grid stratification in
  `subsample_chargers.py` works either way since it's just a uniform
  grid in metres, but any external lat/lon join must project to
  EPSG:26985.
- **Plug-count is the contention gate** in
  `VehicleChargingHandler.java:499`. Scaling plug_count is a valid
  contention lever; do **not** also edit Java to ignore plug_count.
- **No Java rebuild needed** for the hybrid scheme — `ChargerReader`
  reads plug_count verbatim from XML.
- **2-wide parallelism cap** on this workstation (Ryzen 7 2700X, 64 GB).
  Do NOT launch 13 sensitivity cells in parallel.
- **Do not regenerate sub-samples mid-baseline-run** — the running
  prod_100pct does not use sub-samples, but be careful that any
  sensitivity launch reads from the regenerated files (verified by
  manifest timestamp 2026-06-11).
