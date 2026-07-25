# Sub-sampling methodology — calib_10pct and smoke_1pct tiers

How the 10 % (calib) and 1 % (smoke) tiers used by sensitivity analysis and
Phase-5 pipeline shakedown were produced from the full 100 % Maryland inputs.

Source scripts (already in repo):
- `scripts/subsample_population.py`
- `scripts/subsample_chargers.py`

Both are deterministic given `--seed`. The committed sub-samples used
`--seed 4711` (matches `global.randomSeed` in the configs).

---

## 1. Why sub-sample at all

| tier | wall per cell | use case |
|---|---|---|
| 1 % (smoke) | ~30 min | pipeline shake-down, regression checks |
| 10 % (calib) | ~3.5 h | OAT sensitivity, parameter screening |
| 100 % (prod) | ~5 days | publishable baseline, scenario sweep |

The full-scale prod run is too slow for any kind of parameter sweep. The 10 %
tier exists so we can test 10-15 perturbations per week instead of 1 per month.

## 2. What is sub-sampled

| input | full → 1 % → 10 % | sub-sample script |
|---|---|---|
| `Input/population/plans_maryland_ev_clean_anx020.xml.gz` (99,132 persons) | → `plans_md_ev_1pct.xml.gz` → `plans_md_ev_10pct.xml.gz` | `subsample_population.py` |
| `Input/vehicles/electric_vehicles_clean.xml` (one per person) | → `electric_vehicles_clean_1pct.xml` → `electric_vehicles_clean_10pct.xml` | (same script — vehicles file filtered by selected person-IDs) |
| `Input/chargers/chargers.xml` (1,744 chargers) | smoke uses **full** (no sub-sample at 1 % tier) → `chargers_10pct.xml` (194 chargers, 11.1 %) | `subsample_chargers.py` |

Network and vehicle-types files are never sub-sampled — they are not
proportional to agent count.

## 3. Population sub-sampling — `subsample_population.py`

### 3.1 Stratification

2D strata = **(`evType`, `hh_income_detailed`)** read from each `<person>`'s
attributes.

- `evType ∈ {BEV, PHEV}` — 2 levels
- `hh_income_detailed ∈ 0…9` — 10 deciles
- **20 strata**

### 3.2 Allocation rule

Per stratum: `target = stratum_size × sample_fraction`.
Take `n = floor(target) + Bernoulli(target − floor(target))` (floor-with-prob).
This is unbiased for expected total sample size.

Guarantee: when `sample > 0` and a stratum is non-empty, at least 1 person is
kept. Prevents losing rare income × evType combinations entirely.

### 3.3 Output

- Plans XML re-emits selected `<person>` elements (stream-parsed via
  `ET.iterparse` for memory safety on the 21 MB gzipped input).
- Vehicles XML drops any `<vehicle id="...">` whose `id` is not in the
  selected set. The script assumes `vehicle.id == person.id` (verified by
  inspection of the pipeline).
- DOCTYPE preserved manually (MATSim requires it).

### 3.4 Reproducibility

```
cd UrbanEV-Maryland
python scripts/subsample_population.py --sample 0.10 --seed 4711
python scripts/subsample_population.py --sample 0.01 --seed 4711
```

Same seed but different sample fractions → the 1 % is **not** a strict subset
of the 10 % (the per-stratum shuffles are independent under different
sub-sample sizes). If nested samples are needed for a future tier study,
re-seed deliberately.

## 4. Charger sub-sampling — `subsample_chargers.py`

### 4.1 Stratification

2D strata = **(`charger_type`, `grid_cell`)**.

- `charger_type ∈ {L1, L2, DCFC, DCFC_TESLA}` — 4 levels
- `grid_cell` = `(floor(x/50000), floor(y/50000))` in EPSG:26918 (UTM 18N)
  → a 50 km grid yielding ~32 spatial cells across MD
- Upper bound: ~128 strata; actual non-empty count is ~60-80

L1 is **kept verbatim** (only 2 chargers statewide — sub-sampling would be
noise).

### 4.2 Allocation rule

Identical to population: `target = bucket_size × sample`, floor-with-prob,
≥1 per non-empty bucket.

The ≥1 guarantee is what raises the actual 10 % sample to 11.1 % (194 / 1744)
— spatial cells with a single rare-type charger pull up the per-type rate.

### 4.3 Empirical 10 % outcome

From `Input/chargers/chargers_10pct_manifest.json`:

| type | input | kept | kept rate |
|---|---:|---:|---:|
| L1 | 2 | 2 | 100.0 % (verbatim) |
| L2 | 1,391 | 143 | 10.3 % |
| DCFC | 274 | 34 | 12.4 % |
| DCFC_TESLA | 77 | 15 | 19.5 % |
| **total** | **1,744** | **194** | **11.1 %** |

DCFC_TESLA's 19.5 % is the ≥1-per-bucket guarantee inflating sparse cells;
the absolute count is still small.

### 4.4 Reproducibility

```
cd UrbanEV-Maryland
python scripts/subsample_chargers.py --sample 0.10 --seed 4711
# → Input/chargers/chargers_10pct.xml
# → Input/chargers/chargers_10pct_manifest.json
```

The manifest records: input file SHA-256, seed, sample fraction, grid cell
size, per-type counts, and a UTC timestamp. Re-running with same seed/sample
on the same input file is bit-identical.

## 5. Why the calib tier still has a residual spatial-density artifact

Even with the spatial-stratified charger sub-sample described above, the
calib 10 % tier exhibits a **~12 pp upward bias on home-charging share**
compared to the prod 100 % tier (see `analysis/sensitivity_design.md` §2).

Mechanism:
- Numerical agents-to-chargers ratio is preserved (calib 9,915 / 194 = 51;
  prod 99,132 / 1,744 = 57). Contention dynamics are roughly right.
- But **chargers per km² drops 9×** at calib (194 chargers over the same
  ~30,000 km² of MD vs 1,744). With `parkingSearchRadius = 500 m`, the
  probability that any given activity location has *any* reachable public
  charger collapses.
- Agents whose nearest public charger is now >500 m away **cannot use it
  at all** — they default to home if they have a home charger, or fail.
  This artificially inflates home %.

The grid-cell stratification mitigates but does not eliminate this: it
ensures rural cells keep at least one charger, but it cannot increase the
density within a cell.

### 5.1 Implication for sensitivity analysis

This is why `sensitivity_design.md` mandates **Δ-reporting** (differences
from the calib center cell) rather than absolute values. The density
artifact applies equally to all 13 cells of the OAT design, so cancels out
in differences. But:

- **`parkingSearchRadius` cells (R1/R2/R3) interact with the density
  artifact.** A larger radius at calib partially compensates for the lower
  density. Δ magnitudes from R1/R2/R3 are therefore **upper bounds** on
  the effect that would be seen at prod. Documented in §8 of
  `sensitivity_design.md`.

### 5.2 Alternative sub-sampling we considered and rejected

| approach | why rejected |
|---|---|
| Keep all 1,744 chargers + 10 % agents | Agents-to-chargers ratio collapses to 5.7 (vs prod's 57). Public chargers always have free plugs → no contention → over-estimates public share. This is what the calib tier originally used (memory: `feedback_scale_chargers_with_agents`). |
| Sample by county instead of 50 km grid | County file not in chargers.xml; would require an extra GIS join. The 50 km grid has comparable cell count (~32 vs MD's 24 counties) and is self-contained. |
| Density-equalize: sample chargers only in cells that have an agent | Mathematically tricky (cell occupancy depends on the agent sub-sample) and would amplify selection bias. |
| Sample by spatial-Poisson thinning | Would preserve density approximately but not contention ratio — same problem as keeping all chargers, just with extra noise. |

The current stratified design is a compromise: preserves contention ratio
exactly, partially preserves spatial coverage, sacrifices per-km² density.

## 6. Manifests and provenance

Every charger sub-sample run writes a JSON manifest beside the output XML
with:

```json
{
  "purpose": "...",
  "generated_utc": "2026-06-08T14:50:27+00:00",
  "git_sha": "...",
  "source": ".../chargers.xml",
  "source_sha256": "5bf0834ba02bdb4f8604d07b7c38b0a2e2beb178cb3c6bbec510b1263b700cad",
  "rng_seed": 4711,
  "sample_fraction": 0.10,
  "grid_cell_m": 50000,
  "strata": "(charger_type, grid_cell=50000m UTM 18N)",
  "types_kept_verbatim": ["L1"],
  "totals": {"input_by_type": {...}, "kept_by_type": {...}}
}
```

Population sub-sampling does not currently write a manifest. **TODO** for
the sensitivity launch: add a manifest emission to `subsample_population.py`
mirroring the chargers manifest, so the 10 % population sub-sample used by
sensitivity is fully traceable in the manuscript supplementary.

## 7. Reproducing the 10 % calibration tier from scratch

```
cd UrbanEV-Maryland
python scripts/subsample_population.py --sample 0.10 --seed 4711
python scripts/subsample_chargers.py    --sample 0.10 --seed 4711
# generates:
#   Input/population/plans_md_ev_10pct.xml.gz
#   Input/vehicles/electric_vehicles_clean_10pct.xml
#   Input/chargers/chargers_10pct.xml
#   Input/chargers/chargers_10pct_manifest.json
```

Then `scenarios/maryland/config_calib_10pct.xml` already references these
paths and is ready for sensitivity launch (see `sensitivity_design.md` §5
for the 13-cell launch sequence).
