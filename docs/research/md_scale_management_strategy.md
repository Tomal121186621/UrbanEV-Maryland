# Phase 0.8 — Scale Management Strategy

**Drafted:** 2026-06-08
**Scope:** 99,132 EV-owning agents × 695k MD network links × 168h simulated week × 50–200 MATSim iterations.
**Purpose:** Define the sub-sample tiers, MATSim capacity-scaling conventions, charger-scaling
policy, memory/disk/wallclock envelopes, and iteration plan that will get us from
smoke-test through production without hitting the wall on resources or wasting compute on
tuning at full scale.

---

## 1. Two sub-sample tiers (REVISED 2026-06-08 — calib-10% tier REMOVED)

| Tier            | Agents | Sample | Iterations | Purpose                                           | Wall budget (est.) |
| --------------- | -----: | -----: | ---------: | ------------------------------------------------- | ------------------ |
| **smoke 1%**    |    991 |   1%   |     50     | Pipeline shakedown only — no calibration claims   | < 1 h              |
| **prod 100%**   | 99,132 | 100%   |    150     | Calibration (BO) + scenario sweep + headline      | ~24-36 h calib; ~2.5 d sweep |

**Why calib-10% tier was removed:** per-charger demand is not uniform — it emerges from the
joint distribution of `charger_location × agent_activity_coords × time-of-day`. Examples in MD:
- DCFC at I-95 Wawa: ~80% utilization (long-haul commuters)
- 1-plug L2 at dentist office: ~2% (incidental visitors)
- Apartment-garage L2: captive tenant demand only
- Workplace L2: ~50 employees, weekday daytime only

ANY sub-sampling of EITHER agents OR chargers breaks the joint distribution that produces
this heterogeneity. Plug-count scaling assumes uniform demand-per-plug (wrong). Stratified
charger sampling assumes within-stratum interchangeability (wrong). Therefore at any tier
< 100%, the contention-sensitive quantities (per-station occupancy, queueing disutility,
type-switching driven by L2-busy → DCFC) cannot be faithfully measured. Since the
load-bearing claims of the paper (the $22.4M revenue gap and its scenario-induced shifts)
depend precisely on these contention-sensitive quantities, calibration at sub-sample tier
would put a defensible-looking number on top of an indefensible scaling assumption.

**Sub-sampling method (for 1% smoke only):** stratified random by
(`archetype` × `home_county_FIPS` × `income_decile`) with proportional allocation.
Implemented as `scripts/subsample_population.py`. The 1% sample exists purely to verify the
code path executes — non-zero counts per charger type, no crashes, score convergence over
50 iters. No quantitative claim from 1%.

---

## 2. MATSim flow/storage capacity scaling

MATSim requires `flowCapFactor` and `storageCapFactor` to be set proportional to sample so
non-EV background traffic does not vanish and so EV agents themselves do not artificially
clog links.

| Tier        | flowCapFactor | storageCapFactor |
| ----------- | ------------: | ---------------: |
| smoke 1%    |          0.01 |             0.03 |
| prod 100%   |          1.00 |             1.00 |

**Storage = 3× flow convention** (MATSim default for sparse sample) — prevents
spurious gridlock that occurs when sub-sample's storage caps round down to integers and
links underflow.

**EV-agent share caveat:** the 99k EV population is itself only ~1.5% of MD's ~6.6M licensed
drivers. We are NOT simulating non-EV background traffic in v1 (no `plans_md_all.xml.gz`).
Therefore the flowCapFactor only governs link-level congestion among the EV-only fleet, which
will under-represent true MD network congestion. **Documented limitation** — Phase 5
re-evaluates whether to import a 1% background-traffic plan from MWCOG TPB if validation
shows EV-only travel times are unrealistically short.

---

## 3. Charger scaling policy (REVISED AGAIN 2026-06-08 — no calibration at sub-sample)

The full 1,744-charger MD inventory is used at BOTH tiers. No charger sub-sampling.
- `config_smoke_1pct.xml` → `chargers.xml` (full)
- `config_prod_100pct.xml` → `chargers.xml` (full)

**Why no sub-sampling at any tier:** see §1 for the demand-heterogeneity argument. Briefly:
contention per charger depends on the joint `charger × agent × time` distribution, which is
non-uniform across stations (I-95 DCFC vs. apartment-garage L2 vs. workplace L2 see wildly
different demand sheds). Sub-sampling either side breaks the joint, and no plug-scaling or
stratified-entity scheme can recover it without already knowing the demand-shed for each
charger (which would presuppose the simulation result).

**At 1% smoke tier:** the full charger network with 991 agents gives effectively zero
contention (one agent per 1.76 chargers). The 1% tier is therefore explicitly NOT used for
calibration — only for code-path verification.

---

## 4. Memory / disk / I/O envelopes

### Heap requirements (MATSim 12.x rules of thumb, JDK 17 G1 GC)

| Component                          | Per-unit cost | 1%      | 100%      |
| ---------------------------------- | ------------: | ------: | --------: |
| Agent state + selected plan        | ~2 KB / agent | 2 MB    | 200 MB    |
| Plan-choice-set memory (5 plans)   | ~8 KB / agent | 8 MB    | 800 MB    |
| Network graph (695k links, routed) |             — | 600 MB  | 600 MB    |
| TravelTime cache (15-min bins)     |             — | 300 MB  | 300 MB    |
| Events buffer (in-flight)          | scales w/ pop | 100 MB  | 2 GB      |
| Charger state (1744 chargers)      |             — | < 10 MB | < 10 MB   |
| JVM overhead + JDK 17 baseline     |             — | 500 MB  | 500 MB    |
| **Recommended `-Xmx`**             |               | **4 G** | **24 G**  |

Note: network + TravelTime cache dominate at small sample. Production needs 24 GB minimum;
30–32 GB safer headroom.

### Disk requirements (events + plans + iteration output)

| Artifact                                | Per iter cost          | 50-iter smoke | 150-iter prod |
| --------------------------------------- | ---------------------- | ------------: | ------------: |
| `output_events.xml.gz` (every Nth iter) | ~0.5 MB/k-agent        | 25 MB         | ~37 GB raw    |
| Plans (every Nth iter)                  | ~0.2 MB/k-agent        | 10 MB         | ~3 GB         |
| `chargingBehaviorScores.csv` (every it) | ~10 KB/iter            | 0.5 MB        | 1.5 MB        |
| Network snapshot (initial only)         | ~80 MB once            | 80 MB         | 80 MB         |
| **Tier disk budget**                    |                        | **150 MB**    | **45 GB**     |

**Critical config knobs to keep prod disk under 100 GB:**
- `writeEventsInterval = 25` (only iter 0, 25, 50, ..., 150 keep events) → 6 events files at 100%
- `writePlansInterval  = 50` (only iter 0, 50, 100, 150) → 4 plans files
- `writeSnapshotsInterval = 0` (no snapshots — we don't need movement playback)
- `events.fileFormat = "xml"` not "pb" (MATSim 12 PB format saves ~50% but our event consumers
  read XML; revisit only if disk becomes the bottleneck)

### Wall-clock cost model

MATSim 12.x throughput at JDK 17 on a typical workstation (8-core, 32 GB):
- Per-iteration cost ≈ `c × N_agents × log(L_network)`, with `c ≈ 1.5 ms/agent` empirically
- 1%: 991 × 1.5 ms × 50 ≈ 75 s + I/O ≈ **2 min/run**
- 100%: 99,132 × 1.5 ms × 150 ≈ 6.2 h + I/O ≈ **8 h/run** sequential

### Bayesian-optimized 100% calibration plan (CONFIRMED 2026-06-08)

Calibration is performed directly at 100% full-Maryland scale via Bayesian
optimization over {`betaMoney`, `α_scaleCost`, optionally `publicL2Cost` /
`publicDcfcCost`} minimizing KL-divergence against EVWatts MD session-energy
distribution + Pearson-r against ChargePoint MD per-station occupancy.

**Target hardware:** Ryzen 7 2700X (8c/16t, Zen+ 2018), 64 GB RAM,
4 TB SATA SSD. No HPC available.

| Item                                          | Value                                       |
| --------------------------------------------- | ------------------------------------------- |
| BO budget                                     | ~12 cells (BoTorch / scikit-optimize)       |
| Per-cell wall (100%, 150 iter, Zen+ silicon)  | **~10 h** (2 ms/agent empirical)            |
| Parallelism (memory-limited: 24 GB heap each) | **2-wide** (3-wide would oversubscribe RAM) |
| Calibration wall total                        | **~60 h** (~12/2 batches × 10 h ≈ 2.5 d)    |
| Phase 7 scenario sweep                        | 24 cells × 10 h / 2-wide = **~120 h ≈ 5 d** |
| Validation re-runs + held-out cells           | **~20 h** (~1 d)                            |

**Total compute budget = ~8 days workstation wall** (smoke + calibration +
scenarios + validation).

If wall slips, fallbacks: (a) cut BO 12→8 cells, (b) cut Phase 7 24→12 cells
(drop one sweep axis).

**These estimates need ground-truthing against the smoke-1% wallclock** — first prod
estimate will be re-derived from the smoke run's actual `iter*.json` timing.

---

## 5. Iteration plan (warmup vs scoring split)

Coevolutionary MATSim convergence pattern:
1. **Innovation phase** (iters 0 to 0.8×lastIter): full replanning, all modules active
   (`ChangeChargingBehaviourModule`, time-mutator, route-mutator).
2. **Scoring phase** (last 20% of iters): innovation off, only `SelectExpBeta` re-weights
   existing choice set. Stabilizes scores for validation snapshot.

Per-tier `lastIteration` and `disableInnovationAfterIteration`:

| Tier        | lastIteration | disableInnovation | Rationale                                          |
| ----------- | ------------: | ----------------: | -------------------------------------------------- |
| smoke 1%    |            50 |                40 | Just verify scoring converges in scoring phase     |
| prod 100%   |           150 |               120 | Larger choice space, slower mixing                 |

**Convergence test:** `score_history.csv` slope over last 10 iters of innovation phase
should be < 0.5% of mean score (Parishwad criterion). If failing, extend by 50 iters.

---

## 6. Config file mapping

Phase 2 will create two sibling configs in `scenarios/maryland/`:

| Config file                       | Tier      | flowCapFactor | lastIter | -Xmx in launcher |
| --------------------------------- | --------- | ------------: | -------: | ---------------: |
| `config_smoke_1pct.xml`           | smoke     |          0.01 |       50 |              4g  |
| `config_prod_100pct.xml`          | prod      |          1.00 |      150 |             24g  |

Plans file path differs by config. Chargers/network/vehicles paths identical across both
tiers (full infrastructure at both, per revised §3).

---

## 7. Open items routed to Phase 5 / Phase 7

- **Background-traffic decision:** import 1% MWCOG TPB plan or run EV-only? (Phase 5)
- **β_money rescaling check:** confirm 10%-tier calibration transfers to 100% (Phase 5)
- **Scenario-sweep parallelism:** 24-cell sweep at 100% × 8 h = 192 core-hours; do we
  parallelize 4-wide on workstation or migrate to UMD cluster? (Phase 7)
- **Events PB format adoption:** revisit if prod disk > 100 GB (Phase 7)

---

## 8. Hardware questions for user

To finalize wallclock envelope, need confirmation of:
1. Available RAM on primary workstation (need 24 GB free for prod tier; 32 GB safer)
2. Core count + base clock (calibration iteration time scales near-linearly with cores up to
   ~16 for our 99k pop)
3. SSD vs HDD for `output/` (events writes are I/O-heavy; HDD adds ~30% wall-time)
4. Whether UMD cluster access is available for the Phase 7 scenario sweep
