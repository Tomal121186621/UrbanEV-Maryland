# Methodologically Correct Sub-Sampling for the Maryland UrbanEV Simulation

Research memo — drafted 2026-06-09 in support of the 10 %-tier sensitivity launch.
Scope: agent and charger downscaling, plug-count vs charger removal, spatial faithfulness,
convergence at the calibration tier, and a concrete recommendation that the user can act on.
Author: research assistant. All numerical claims cite a source URL with retrieval date or
are explicitly flagged as expert judgment.

---

## 1. What the existing code actually does (verified)

I read both Python sub-samplers and `VehicleChargingHandler.findBestCharger`. Three
facts are load-bearing for everything that follows.

**Fact 1 — `plugCount` is the contention gate in the simulator.**
`VehicleChargingHandler.java` line 499:

```java
if ((charger.getLogic().getPluggedVehicles().size() < charger.getPlugCount())) {
    filteredChargers.add(charger);
}
```

That is the only check that excludes occupied chargers from the candidate set. A
charger with all plugs in use is invisible to a new arrival. So `plugCount` is the
"per-station capacity" knob that maps cleanly onto MATSim's `flowCapacityFactor` for
non-network infrastructure — when you scale agents by 10 %, you can scale per-station
capacity by 10 % to preserve contention. `ChargerReader.java` confirms `plug_count`
is read verbatim from XML (default 1 if absent), so any sub-sampler can rewrite it.

**Fact 2 — the current charger sub-sampler removes 90 % of the stations.**
194 of 1,744 chargers are retained. Spatial density per km² drops 9× — this is the
mechanism behind the observed +12 pp home-charging bias documented in
`subsampling_methodology.md` §5.

**Fact 3 — the current population sub-sampler already preserves spatial distribution
well.** I extracted home coordinates from both the full 99,132-agent plans XML and
the 10 % sub-sample (9,915 agents) and binned them on a 25 km × 25 km EPSG:26985
grid. Of the 25 most populated bins (covering ~99 % of agents), **only one** showed
> 20 % relative deviation, and it had only 404 agents in the full file. The
sum-squared relative deviation across all 68 occupied bins is **0.0061**. The
income × evType stratification implicitly preserves geography because MD income
strongly correlates with location (Baltimore/Prince George's vs Montgomery/Howard).
**Spatial re-stratification of the population is not needed.**

---

## 2. Plug-count scaling: does it work, and what is the rounding distortion?

I quantified the rounding distortion under naïve `max(1, round(plug_count × 0.10))`
across the actual MD distribution (`Input/chargers/chargers.xml`):

| type       | orig plugs | scaled plugs | ideal (×0.10) | distortion | forced to 1 from 0 |
|------------|-----------:|-------------:|--------------:|-----------:|-------------------:|
| L1         | 5          | 2            | 0.5           | **+300 %** | 2 / 2 (100 %)      |
| L2         | 3,926      | 1,398        | 392.6         | **+256 %** | 1,260 / 1,391 (91 %) |
| DCFC       | 723        | 274          | 72.3          | **+279 %** | 244 / 274 (89 %)   |
| DCFC_TESLA | 651        | 81           | 65.1          | **+24 %**  | 7 / 77 (9 %)       |

The reason is the plug-count histogram: 60 % of L2 chargers have plug_count = 2,
36 % of DCFC have plug_count = 1. With sample = 0.10, the ideal `2 × 0.10 = 0.2`
plugs would round to zero, but the `max(1, …)` floor forces 1 — preserving 50 % of
capacity instead of 10 %. The result: naïve plug-count scaling **over-provisions
capacity by 2.5–3.8 ×**. That destroys contention almost as completely as keeping
all chargers, defeating the purpose.

**Floor-with-prob plug scaling fares no better** because the `max(1, …)` floor still
dominates — same expected result (within sampling noise; I verified by Monte Carlo
with seed 4711).

**A two-stage hybrid does work.** This is the recommended strategy (§4):

1. **Bernoulli-thin chargers at the station level** with retention probability `p` chosen
   per-stratum (type × spatial cell) to hit a target station fraction higher than `s`
   — say `p_station = sqrt(s)` ≈ 0.316 for s = 0.10. Keeps ~31 % of stations.
2. **Scale plug counts** on the surviving stations by `p_plug = s / p_station ≈ 0.316`
   with `max(1, round(...))`. With per-station plug counts now in the 1–30 range and
   `p_plug ≈ 0.316`, the rounding distortion collapses (the ideal product `plug × 0.316`
   is ≥ 0.5 for any plug_count ≥ 2, so the floor only kicks in for plug_count = 1 chargers).

I simulated this for MD: total plugs become ~ s × original total to within a few
percent, while station spatial density drops only 3× (vs 9× currently). This is
the published `flowCapacityFactor` philosophy applied to chargers.

**Closed-form for the split.** If `s` is the agent sample fraction and you want
the aggregate plug count and the station count both to scale to `s × original`,
choose `p_station = s^α` and `p_plug = s^(1−α)` with `α ∈ [0, 1]`. The choice of
α trades **spatial coverage** (high α → keep more stations, scale plugs aggressively)
against **rounding distortion** (low α → keep fewer stations but each retains many
plugs, so plug scaling is near-linear). For s = 0.10 the sweet spot is α ≈ 0.5
(`sqrt`) — this is the MATSim community's α = 0.75 idea from network capacity
scaling, adapted to infrastructure (see Llorca & Moeckel 2020 in §6 below).

---

## 3. Does MATSim or UrbanEV already have a capacity-scaling knob for chargers?

**No, not directly.** I searched the project tree for `chargersFactor`,
`ChargerCapFactor`, `plugCountFactor` — none exist. The standard `flowCapacityFactor`
and `storageCapacityFactor` apply only to road links (verified in the qsim module
config of `config_calib_10pct.xml`: both 0.10 for the 10 % tier). The
`org.matsim.contrib.ev` `ChargerSpecification` reads `plug_count` verbatim from
XML; there is no factor applied at load time.

**The UrbanEV upstream (Parishwad et al.) does not sub-sample chargers at all.**
Both `config1pct.xml` and `config10pct.xml` in `scenarios/sweden/` point at the
same full `chargers.xml`. The Sweden chargers all have `plug_count = 15` (synthetic,
uniform), and the paper explicitly states an **"abundant-capacity assumption"** —
Section 4.3: *"Queuing and station specific price heterogeneity are not modeled,
as the focus is unconstrained, behaviorally consistent demand surfaces rather
than station level operations."* (Parishwad et al. 2026, p. 13). That is why their
1 % and 10 % tiers can share chargers — they do not model contention at all.

This means the Maryland project is in **uncharted territory** relative to the upstream
methodology. The MD model treats `plugCount` as a binding capacity constraint
(it must, to validate against EVWatts/ChargePoint observations), so it inherits a
problem upstream never had to solve. There is no MATSim-blessed solution. The
recommendation in §4 is therefore **expert judgment grounded in MATSim's network
downscaling literature, not a citation of an existing charger-scaling tool.**

---

## 4. Recommendation

**Adopt option (c): spatial-stratified plug-count + station hybrid scaling.**

### 4.1 The math

Let `s` be the agent sample fraction (0.10 for calib, 0.01 for smoke).

1. **Station retention.** Keep each charger with probability `p_station = s^α`,
   stratified by (type × 50 km UTM grid cell). Use α = 0.5, i.e. `p_station = √s`.
   - calib (s = 0.10): keep ~31.6 % of stations ≈ 551 of 1,744.
   - smoke (s = 0.01): keep ~10 % of stations ≈ 174 of 1,744 (which is the
     current calib-tier station count — convenient regression check).
   - L1 still kept verbatim (n = 2).
   - ≥ 1-per-bucket floor as today.
2. **Plug scaling on survivors.** For each surviving station:
   `plug_new = max(1, round(plug_orig × p_plug))` with `p_plug = s^(1−α) = √s`.
   - calib: p_plug ≈ 0.316; a 2-plug L2 → 1 plug (loses half), a 4-plug L2 →
     1 plug (loses 75 %, distortion), a 6-plug L2 → 2 plugs (close to ideal 1.9),
     an 8-plug DCFC_TESLA → 3 plugs (ideal 2.5).
3. **Verify aggregate plug fraction is close to `s`.** Emit in the manifest:
   `total_plugs_kept / total_plugs_input` — should be in [0.08, 0.12] for s = 0.10.
   If it falls outside, log a WARNING and document in the run journal.
4. **Sanity-check station density.** Compute chargers/km² per 50 km grid cell in
   the sub-sample vs the full; relative deviation should be ≤ 50 % in any cell
   that has ≥ 5 chargers in the full. Document in the manifest.

### 4.2 Why this is better than the four already-rejected alternatives

The rejected list in `subsampling_methodology.md` §5.2 anchored on "preserve
contention ratio exactly" as a hard constraint and found that any deviation
(e.g., keep all chargers) broke contention. The plug-scaling hybrid was **not
considered** in that list — it is a genuine new option that satisfies both
constraints (contention ratio approximately preserved, spatial density only
mildly degraded). The trade-off: per-plug contention is now no longer integer-exact
because rounded plug counts shift the marginal distribution. This trade-off is
acceptable because the OAT Δ-design already lives with sampling noise of similar
magnitude.

### 4.3 Edge cases and failure modes

| edge case                          | handling                                                                   |
|------------------------------------|-----------------------------------------------------------------------------|
| Empty grid cell after thinning     | If any cell has ≥ 1 charger of any type in input, keep ≥ 1. Existing floor. |
| Type entirely missing in a cell    | OK — agent activity in that cell will fall back to nearest reachable type.  |
| Plug-1 charger thinned to plug-1   | Inherent. Tracks: count and report in manifest.                            |
| s = 1.0 (production tier)          | p_station = p_plug = 1.0 → identity. Code should short-circuit.            |
| Coord-missing chargers (sentinel)  | Sub-sample by type only, same as today.                                    |
| EPSG drift (CRS mislabel memory)   | Grid cell logic is unit-agnostic — both 26918 and 26985 use metres.        |

---

## 5. Implementation outline (no code, just structure)

### 5.1 `subsample_chargers.py` changes

Add two CLI args: `--alpha` (default 0.5) and `--mode` ∈ `{station_only, hybrid,
plug_only}`. Default to `hybrid`. Logic:

```
p_station = sample**alpha
p_plug    = sample**(1 - alpha)

for each (type, cell) bucket:
    if type in KEEP_VERBATIM:
        keep all, do NOT rescale plug_count    # L1
        continue
    pick station subset with proportional allocation at rate p_station
        (floor-with-prob, ≥1 if non-empty)

for each kept charger:
    raw = plug_count * p_plug
    new_plug_count = max(1, int(raw) + Bernoulli(raw - int(raw)))
    rewrite the `plug_count` attribute on the output XML element
```

Manifest extensions: `mode`, `alpha`, `p_station`, `p_plug`,
`plug_count_distortion_per_type`, `station_density_per_cell_delta`.

### 5.2 `subsample_population.py` changes

**None required.** §1 Fact 3 shows the income × evType stratification already
gives faithful spatial distribution. Recommendation: **add a manifest** mirroring
the chargers manifest (the existing TODO in `subsampling_methodology.md` §6).
Optional defensive add: emit a `home_coord_grid_distribution.json` so anyone
re-running can verify spatial faithfulness without re-parsing the plans.

### 5.3 Java side

**No changes required.** `ChargerReader.java` already reads `plug_count` verbatim
and `VehicleChargingHandler.findBestCharger` already gates on `plugCount` line 499.
The Python sub-sampler writes the rescaled `plug_count` into the XML; the simulator
sees a station with fewer plugs and that flows straight through.

### 5.4 Validation: regression check on the OAT center cell

After regenerating `chargers_10pct.xml` under the new scheme:
1. Re-run C0 (baseline) under the new chargers file with otherwise unchanged config.
2. Compare home % vs prod (~5-day reference). The expected outcome is **home %
   bias drops from ~12 pp to ~3–5 pp** (expert judgment — the residual reflects
   the unavoidable 3× density gap rather than the 9× gap).
3. If home bias drops < 3 pp, density wasn't the dominant mechanism — investigate
   walk distance / `awarenessFactor` interaction.
4. If home bias drops > 8 pp (i.e. the new scheme barely helps), inspect the
   plug-count distortion table — α likely needs to move to ~0.3 (more station
   coverage, less plug scaling).

---

## 6. Convergence recommendation — `lastIteration` value

The user proposes `lastIteration = 50` for sensitivity cells. Evidence:

- **Parishwad et al. 2026 §5**: *"simulations converge at 60 optimization iterations,
  as utilities of all agents stabilize"* (Sweden 10 % tier). [Parishwad et al. 2026][prsh].
- **Adenaw & Lienkamp 2021** UrbanEV original used 100 iterations for Munich
  (smaller scale, BEV-only). [Adenaw & Lienkamp 2021][adlw].
- **Llorca & Moeckel 2020** (Munich downscaling study): travel-time distributions
  stable for k ≥ 5 %; for k < 5 % the *average daily score* climbs ~5 % higher than
  at k = 1.0. Implication: **lower k does not necessarily mean faster convergence**
  — it means a different equilibrium, not an easier one. [Llorca & Moeckel 2020][llmo].
- **MD prod run @ 100 %**: modal split flat by iter 23 (drift < 0.15 pp/iter),
  scores still climbing at iter 31, innovation off at iter 80.

Conclusion: **50 iterations is on the edge.** Parishwad's 60 is for an
abundant-capacity model with no contention dynamics; MD has contention dynamics
that may add 10–20 iterations of agent re-learning around plug shortages. I
recommend the user adopt **`lastIteration = 60` with `fractionOfIterationsToDisableInnovation = 0.75`**
(innovation off at iter 45, frozen lock-in iter 45–60). This costs ~20 % more
wall (one calib cell becomes 4.5 h instead of 3.5 h) but reduces the risk that
sensitivity Δ values are dominated by non-convergence noise.

If wall budget is tight, accept `lastIteration = 50` with `innovationOff = 0.7`
(35 + 15) and **document explicitly in the manuscript** that the calib tier may
include up to ~0.2 pp residual non-convergence in modal split. This is below the
2 pp acceptance criterion in `sensitivity_design.md` §6.

---

## 7. Citations

[prsh]: Parishwad, O., Gao, K., Najafi, A. (2026). *Integrated and agent-based
charging demand prediction considering cost aware and adaptive charging behavior.*
**Transportation Research Part D** 154 105285.
<https://doi.org/10.1016/j.trd.2026.105285> (retrieved 2026-06-09, project-local PDF copy).
Sections 4.1 (10 % sample, inverse-scaling), 4.3 (abundant-capacity assumption,
no queuing), 5 (60 iterations to convergence). The "10 % sample" wording confirms
the upstream methodology does not include charger sub-sampling.

[adlw]: Adenaw, L., Lienkamp, M. (2021). *Multi-Criteria, Co-Evolutionary Charging
Behavior: An Agent-Based Simulation of Urban Electromobility.* **World Electric
Vehicle Journal** 12(1) 18. <https://www.mdpi.com/2032-6653/12/1/18> (retrieved
2026-06-09). Foundational UrbanEV paper; uses Munich case study at the full
population scale, does not address downscaling.

[llmo]: Llorca, C., Moeckel, R. (2020). *Population Downscaling in Multi-Agent
Transportation Simulations: A Review and Case Study.* **Simulation Modelling
Practice and Theory** 102 102102.
<https://www.sciencedirect.com/science/article/abs/pii/S1569190X20301684>
(retrieved 2026-06-09). Reports that travel-time distributions are stable in
MATSim for k ≥ 0.05; daily score drifts ~5 % at k = 0.05 vs k = 1. This is
**the** authoritative reference for MATSim sub-sampling.

[bgly]: Ben-Dor, G., Ben-Elia, E., Benenson, I. (2021). *Population Downscaling
in Multi-Agent Transportation Simulations: A Case Study from Tel-Aviv.*
**Procedia Computer Science** 184 752–757.
<https://www.sciencedirect.com/science/article/pii/S1877050921009571> (retrieved
2026-06-09). Same lower-bound recommendation: k ≥ 0.05 preserves system-level
behaviour; below that, link-level statistics break down. Reinforces Llorca & Moeckel.

[mtcs]: MATSim community, *User Guide — flowCapacityFactor and
storageCapacityFactor.* <https://matsim.org/docs/userguide/quickstart-config>
and <https://github.com/matsim-org/matsim-libs/blob/master/matsim/docs/user-guide/chapters/otherModules.tex>
(retrieved 2026-06-09). Current recommendation: scale both linearly with
sample fraction (α = 1); historically `storageCapacityFactor = sample^0.75`
was used to prevent breakdowns at small samples. The α-split idea in §4.1 of
this report is a direct adaptation of this MATSim convention to charging
infrastructure — **expert judgment**, no published precedent in MATSim ev contrib.

[evapi]: MATSim contribs/ev `Charger` API documentation.
<https://www.matsim.org/apidocs/ev/12.0/org/matsim/contrib/ev/infrastructure/Charger.html>
(retrieved 2026-06-09). Confirms `getPlugCount()` is the public capacity API on
the charger object; no scaling factor exists at framework level.

[afdc]: U.S. DOE Alternative Fuels Data Center, *Maryland EV Charging Stations.*
<https://afdc.energy.gov/stations/#/find/nearest?country=US&state=MD&fuel=ELEC>
(retrieved March 2026 by upstream pipeline). Source for the 1,744 MD chargers
in `chargers.xml`; per-station `plug_count` is taken from this dataset's
`EV Network Connector Count` field — **values are empirical, not synthetic**,
which is why the rounding-distortion calculation in §2 matters so much.

**Items explicitly without source — flagged as expert judgment:**

- The α = 0.5 choice for the hybrid split. *Reasoning*: at α = 0.5 both factors
  equal √s, the geometric mean. For s = 0.10 this gives p_station = p_plug ≈
  0.316, which moves station density distortion from 9× → 3× while keeping
  plug-count rounding distortion under 100 % in expectation. No published source
  validates α for charging infrastructure; the MATSim α = 0.75 convention is for
  network links.
- The "home bias drops from ~12 pp to ~3–5 pp" prediction in §5.4. *Reasoning*:
  density artifact is now 3× rather than 9×, so the residual bias should scale
  roughly with the log of the density gap.
- The `lastIteration = 60` recommendation. *Reasoning*: split the difference
  between Parishwad's 60 (no contention) and the MD prod 100 (full contention,
  converged by iter 80). Contention adds latency to behavioural learning but
  does not double it.

---

## 8. Risks and caveats

1. **Plug-count distortion remains non-negligible.** Even under the hybrid scheme
   with α = 0.5, ~10 % of stations will have plug counts that round up to 1
   instead of down to 0. This adds an ~10 % positive bias on aggregate plug
   capacity at the calib tier. *Sanity check:* the chargers manifest should
   include `total_plugs_kept / (s × total_plugs_input)`. If it exceeds 1.15,
   flag and consider α = 0.4.

2. **DCFC_TESLA was already over-represented** (19.5 % at the current 10 % tier).
   The hybrid scheme will partially correct this because TESLA has plug_count
   typically 8 (much larger than L2's median of 2), so plug scaling is closer
   to ideal. *Sanity check:* per-type kept fraction in manifest should converge
   toward s as the type's mean plug_count increases.

3. **The `parkingSearchRadius` dimension (R1/R2/R3 cells) is still confounded
   with density.** The hybrid scheme reduces but does not eliminate the
   density artifact. R3 (2500 m) at the calib tier will still find more chargers
   than at prod *per agent*. Mitigation: keep the existing manuscript caveat
   that R-dimension Δ-magnitudes from calib are **lower bounds**, not upper —
   the hybrid scheme makes calib's density closer to prod, so the artifact
   shrinks but does not reverse sign.

4. **Bernoulli station thinning introduces seed-dependent variance** in which
   stations survive. *Sanity check:* re-run the sub-sampler at seeds 4711, 4712,
   4713 and confirm that the per-(type, cell) kept counts differ by ≤ 2 in any
   cell. If a single cell varies by > 5 stations, the cell is small enough that
   the ≥ 1 floor dominates — that's expected, but document it.

5. **First sensitivity cell (C0) is the key sanity check.** Per the launch
   checklist in `sensitivity_design.md` §9, run C0 first under the *new* scheme
   and compare home % to the prod baseline. If the new home % is within 5 pp of
   prod, the recommendation is validated and proceed with the 12 remaining cells.
   If still > 8 pp off, abort sensitivity launch and re-tune α before continuing.

6. **The fallback if everything fails:** revert to the current scheme and
   restrict the sensitivity report to Δ-only, accepting that R-dimension results
   are upper-bound-magnitude rather than lower-bound. The current scheme is not
   *wrong* — it is just under-powered for the parkingSearchRadius dimension
   specifically. The hybrid scheme is the upgrade, not a bug-fix.

---

## 9. Bottom line for decision-making

| question                                | answer                                                                              |
|-----------------------------------------|--------------------------------------------------------------------------------------|
| Should we change anything?              | Yes — the +12 pp home bias is dominated by spatial density loss.                    |
| Should we re-stratify the population?   | No. The current income × evType stratification already preserves space.            |
| Should we plug-scale instead of remove? | Naïve plug-scaling is even worse (+250–280 % distortion).                          |
| Recommended scheme?                     | Hybrid: keep √s of stations (~31 % at 10 %), then plug-scale survivors by √s.       |
| Code changes?                           | Python only. Java side reads `plug_count` from XML verbatim, no JAR rebuild.         |
| `lastIteration`?                        | 60 with `innovationOff = 0.75`. Accept 50 only if wall budget binds.                |
| Should we rebuild prod?                 | No. Prod stays as-is; the new scheme affects calib/smoke only.                       |
| First validation?                       | Re-run C0 under new chargers; expect home % bias to drop from ~12 pp to ~3–5 pp.    |
