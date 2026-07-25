# Sensitivity Analysis — OAT Design (calib_10pct tier)

Drafted 2026-06-09. Operational document — do not launch until the running prod
baseline (task `bkq7pd6lz`, PID 58416) completes and its modal split is recorded
as the central reference point.

## 1. Objective

Quantify the marginal effect of each free model parameter on the headline
outputs (home %, public-L2 %, public-DCFC %, public-charging revenue) using
one-at-a-time (OAT) perturbation around a calib-tier center point. The goal is
**parameter ranking by influence**, not absolute calibration. The 1-2 most
influential dimensions identified here will be re-tested at prod scale in a
follow-up confirmation step.

## 2. Why calib tier, not prod

- 1 prod run ≈ 5 days wall. 13 prod cells = ~9 weeks. Infeasible on the
  workstation (Ryzen 7 2700X / 64 GB / no HPC).
- 1 calib run ≈ 3.5-4 h wall. 13 calib cells = ~2.2 days sequential. Feasible.
- Documented caveat: calib has a ~10× lower charger spatial density per km²
  than prod (see project memory `feedback_scale_chargers_with_agents`). This
  means absolute home-share values from calib are biased upward (~12 pp higher
  than prod), but **relative effects** — the direction and order of magnitude
  of each parameter's impact — transfer cleanly because all cells share the
  same density bias. Report results as `Δ(home %)` per perturbation, not as
  absolute home %.

## 3. Center point (baseline cell C0)

Copy of `scenarios/maryland/config_calib_10pct.xml` with no edits. All 12
perturbed cells deviate from C0 in exactly one parameter.

| param | C0 value | source |
|---|---|---|
| `parkingSearchRadius` | 500 m | upstream default |
| `betaMoney` (in `urban_ev`) | -1.0 | upstream default; per-agent override in plans XML |
| `publicChargingCost` | 0.40 USD/kWh | Phase 4 MD weighted public |
| `homeChargingCost` | 0.139 USD/kWh | BGE residential flat avg |
| `awarenessFactor` | 0.3 | upstream default |
| `defaultRangeAnxietyThreshold` | 0.20 | upstream default |
| `lastIteration` | 50 | enough for modal-split convergence in calib |
| `randomSeed` (global) | 4711 | **must be identical across all 13 cells for paired comparison** |
| `qsim/numberOfThreads` | 6 | applied in fork |

## 4. Perturbed cells

5 parameters × 2-3 levels each = **12 perturbed cells + 1 center = 13 total**.

| cell | varied param | value | rationale |
|---|---|---|---|
| C0 | (center) | — | baseline |
| **R1** | `parkingSearchRadius` | **1000 m** | mid-suburban walking distance |
| **R2** | `parkingSearchRadius` | **1500 m** | broad suburban acceptance |
| **R3** | `parkingSearchRadius` | **2500 m** | rural / corridor upper bound |
| **B1** | `betaMoney` | **-0.5** | half elasticity |
| **B2** | `betaMoney` | **-1.5** | 1.5× elasticity |
| **B3** | `betaMoney` | **-2.0** | 2× elasticity |
| **P1** | `publicChargingCost` | **0.32 USD/kWh** | -20 % (free-market scenario) |
| **P2** | `publicChargingCost` | **0.48 USD/kWh** | +20 % (premium pricing scenario) |
| **A1** | `awarenessFactor` | **0.1** | low TOU compliance |
| **A2** | `awarenessFactor` | **0.5** | high TOU compliance |
| **X1** | `defaultRangeAnxietyThreshold` | **0.15** | low anxiety |
| **X2** | `defaultRangeAnxietyThreshold` | **0.30** | high anxiety |

### Parameters explicitly NOT in scope (and why)

| param | reason for exclusion |
|---|---|
| `homeChargingCost` | empirically measured from BGE tariff, no policy degree of freedom |
| `homeChargerPercentage`, `workChargerPercentage` | empirically encoded per-agent in plans XML, not a free parameter |
| `flowCapacityFactor`, `storageCapacityFactor` | scale knobs, not behavioral |
| `coincidenceFactor` (0.7) | weak coupling to modal split (smart-charging only) |
| `learningRate`, `BrainExpBeta` | replanning hyperparams; convergence-time only, not equilibrium |

## 5. Operationalization

### 5.1 Directory layout (to be created when launching)

```
scenarios/maryland/sensitivity/
  ├── C0_baseline.xml
  ├── R1_parkRadius_1000.xml
  ├── R2_parkRadius_1500.xml
  ├── R3_parkRadius_2500.xml
  ├── B1_betaMoney_neg0.5.xml
  ├── B2_betaMoney_neg1.5.xml
  ├── B3_betaMoney_neg2.0.xml
  ├── P1_publicCost_0.32.xml
  ├── P2_publicCost_0.48.xml
  ├── A1_awareness_0.1.xml
  ├── A2_awareness_0.5.xml
  ├── X1_rangeAnx_0.15.xml
  └── X2_rangeAnx_0.30.xml

output/sensitivity/
  └── <CELL_ID>/                 ← one MATSim output dir per cell
```

Each config is `config_calib_10pct.xml` with exactly the named parameter
changed and `outputDirectory` set to `output/sensitivity/<CELL_ID>`.

### 5.2 Per-cell output metrics (extracted from final iter)

For iter `lastIteration` (=50) per cell, compute:

| metric | source |
|---|---|
| `pct_home`, `pct_work`, `pct_L2`, `pct_DCFC`, `pct_TESLA` | parse `chargingStats.csv` chargerId suffix (same script as iteration_plots.py) |
| `total_sessions` | row count of chargingStats |
| `pct_L2_fail` | parse main log for `"No charger found .* desiredType=L2"` lines for iter 50 |
| `mean_score` | matsim's scorestats.csv last row |
| `kWh_by_type` | sum `transmittedEnergy_kWh` grouped by type |
| `revenue_proxy_USD` | Σ (kWh × per-type cost) — direct policy variable |
| `smart_defer_count` | grep `SmartChargingScheduler: scheduled` in iter-50 events |

Append one row per cell to `output/sensitivity/results.csv`.

### 5.3 Tornado plot script (to author at launch time)

`analysis/sensitivity_tornado.py` — reads `results.csv`, computes
`Δmetric = cell_value - C0_value` for each cell × metric pair, plots a
horizontal bar chart with parameters on Y-axis sorted by |Δhome %|.

### 5.4 Wall budget and ordering

Sequential schedule (one calib at a time, 6 threads, -Xmx16g):

```
order  cell  est wall  cumulative
  1    C0    4.0 h     4.0
  2    R1    4.0 h     8.0
  3    R2    4.5 h    12.5   (larger radius = more candidates per lookup)
  4    R3    5.0 h    17.5
  5    B1    4.0 h    21.5
  6    B2    4.0 h    25.5
  7    B3    4.0 h    29.5
  8    P1    4.0 h    33.5
  9    P2    4.0 h    37.5
 10    A1    4.0 h    41.5
 11    A2    4.0 h    45.5
 12    X1    4.0 h    49.5
 13    X2    4.0 h    53.5
                     ─────
                     ≈ 2.3 days continuous wall
```

Run order rationale: start with C0 to lock in the reference; then walk
parameters in expected impact order (R first because we already suspect it
dominates).

### 5.5 Minimal fallback (if 2.3 days is too much)

8-cell reduced design — keep R1/R2/R3, B1/B2, A1/A2, plus C0. Drops the price
and range-anxiety dimensions entirely; tests only the three structural
parameters. ~32 h wall ≈ 1.3 days.

## 6. Acceptance criteria for the screening result

The OAT is considered informative when:

- |Δhome %| > 2 pp on at least one cell per dimension (i.e., the parameter is
  not a no-op at the tested perturbation magnitude)
- Run order does not affect outcomes (same seed → deterministic; verify by
  re-running C0 at the end and confirming bit-identical chargingStats)

Identified "high-influence" dimensions are those with the largest |Δ| on:
- `pct_home` (modal split)
- `revenue_proxy_USD` (policy variable)

The top-1 dimension by `Δrevenue_proxy_USD` gets one prod-scale confirmation
run; if budget permits, top-2.

## 7. Reporting (manuscript skeleton)

Add to methods §3: "We performed a one-at-a-time sensitivity analysis at the
calibration tier (10 % subsample) varying [N] parameters across [K] cells
around a center point matching the production-tier configuration. Effects are
reported as differences from the center cell to mitigate the known
charger-density bias in the subsampled tier (Δ-reporting design, see
sensitivity_design.md §2)."

Add to results §4: tornado plot of |Δhome %| (Figure S-1) and
|Δrevenue_proxy| (Figure S-2). Cite the top-ranked parameter(s) in the main
discussion as primary uncertainty drivers.

## 8. Operational risks

1. **Heap accumulation across cells** — each calib run accumulates plan
   history. Ensure JVM process exits cleanly between cells (don't try to
   reuse a JVM); run them as 13 separate `java -jar` invocations.

2. **R3 (2500 m radius) may explode candidate-charger lookup time** — the
   filter loop in `VehicleChargingHandler.findBestCharger` is O(n_chargers)
   per attempt. With 1500-2500 m, candidate sets grow large. Budget extra
   wall headroom (+25 %) on R3 and consider a one-off profiling pass.

3. **Seed identity discipline** — `randomSeed=4711` in global module + same
   `MdEVMain.java` rng seed for awareness assignment. Any drift will produce
   pseudo-effects mistaken for parameter sensitivity. Add a smoke-test:
   run C0 twice, assert chargingStats.csv hashes match.

4. **Calib geographic density artifact** is not removed by Δ-reporting if a
   parameter's effect interacts with density (e.g., `parkingSearchRadius`
   directly counteracts the artifact). For R-dimension, the Δ direction will
   transfer to prod but the Δ magnitude may not. Flag this in the
   manuscript: "R-dimension Δ-magnitudes are lower bounds on prod-scale
   effects."

## 9. Launch checklist (do not execute until prod baseline is in)

- [ ] Prod baseline (PID 58416) has reached `lastIteration=100`
- [ ] Prod modal split, revenue, failure rate are recorded as reference
- [ ] 13 sensitivity configs generated under `scenarios/maryland/sensitivity/`
- [ ] `analysis/sensitivity_runner.sh` written (loops over cells, sequential)
- [ ] `analysis/sensitivity_extract.py` written (post-hoc metric extraction)
- [ ] `analysis/sensitivity_tornado.py` written (plotting)
- [ ] Disk headroom verified — 13 calib outputs × ~700 MB each = ~9 GB
- [ ] No other JVMs running on the box (single 6-thread cell at a time)
- [ ] Tools env sourced: `. ../tools/env.sh`
- [ ] Launch first cell (C0) and verify it ends with the same modal split as
      a prior calib_10pct run (regression check on the OAT center)
