# Maryland Gas-Tax Revenue Baseline — 2026

**Retrieved:** 2026-06-07
**Purpose:** Quantify the gas-tax revenue Maryland is "losing" from EV adoption, to size the per-kWh surcharge scenarios in Phase 7.

---

## 1. Current Maryland motor fuel tax rate

| Component | Rate | Effective |
| --- | --- | --- |
| MD state gasoline tax (current) | **$0.460 / gallon** | through Jun 30, 2026 |
| MD state gasoline tax (next) | **$0.466 / gallon** | from Jul 1, 2026 |
| Federal gasoline tax | **$0.184 / gallon** | (18.3¢ excise + 0.1¢ LUST; constant since 1993 per IRC §4081; IRS Pub 510) |
| **Total at pump (state + federal)** | **$0.650 / gallon** | from Jul 1, 2026 |

**Annual indexing mechanism:** MD Tax-General §9-305(b) — Comptroller adjusts each July 1 based on **CPI only** (annual change capped at 8% YoY). For FY2027 (Jul 1 2026 →), CPI-indexed adjustment was +0.6¢/gal, lifting the rate from $0.460 → $0.466. (The pre-2025 statute contained an additional wholesale-gasoline-price component; that provision was repealed and is not part of the current FY2027 calculation.)

**Sources:**
- https://marylandmatters.org/wp-content/uploads/2026/06/MFT-Memo-2026-_Final.pdf (Comptroller memo)
- https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/instructions/motor-fuel/motor-fuel-rate-chart-fy2026.pdf (FY2026 rate chart; PDF binary — not headlessly extractable; corroborated via CBS Baltimore and Maryland Matters)
- https://www.cbsnews.com/baltimore/news/maryland-gas-tax-increase-2026/
- https://marylandmatters.org/2026/06/01/gas-tax-in-maryland-to-increase-slightly-on-july-1/
- https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gtg&section=9-305&enactments=false (statute)

---

## 2. Shadow gas-tax gap — **computed per-agent from simulated VMT**

**Methodology (corrected, endogenous):** The shadow tax gap is NOT a flat fleet-wide
proxy. It is computed per agent from the agent's **actual MATSim-simulated VMT**,
multiplied by a per-archetype counterfactual ICE fuel economy, multiplied by the
authentic MD state gas-tax rate.

```
ShadowTaxGap = Σ_agent ( VMT_agent_annual_mi × (1 / mpg_counterfactual_archetype) × $0.466/gal )
```

### Why this is correct (and the flat 100k × 480gal × $0.466 = $22.4M is only a sanity check)

- **Heterogeneous VMT**: a Bel Air commuter drives ~45 mi/day; a Baltimore urban
  agent ~8 mi/day. Their shadow tax contributions differ ~6×. A flat average
  hides the spatial/equity signal.
- **Endogenous to scenarios**: under high charging prices, agents may re-plan
  shorter trips or substitute modes (in future extension). VMT itself becomes a
  function of the scenario. A fixed denominator would understate the policy lever.
- **Archetype-specific mpg**: a Tesla Model Y owner's counterfactual ICE is a
  midsize CUV (Toyota RAV4 FWD = 30 mpg combined per EPA), not a compact car.
  A Nissan Leaf owner's counterfactual is a compact (Toyota Corolla LE = 35 mpg).
  The Mach-E owner's is ~23 mpg (Ford Edge 2.0L EcoBoost per EPA). Using
  per-EV-type counterfactual mpg captures real per-vehicle displacement.
- **Equity-tractable**: per-agent gap × per-agent income decile → equity dashboard
  ("which income deciles drive the largest shadow gap and would bear the largest
   per-kWh recovery?")

### Per-agent computation pipeline (Phase 7, post-simulation)

Inputs (from MATSim output `output_smoke_1pct/` or equivalent):
- `output_events.xml.gz` → `LinkLeaveEvent` per (person, link, time)
- `output_network.xml.gz` → link lengths (meters)
- Or simpler: `output_legs.csv` / `output_trips.csv` with `traveled_distance` column
- Vehicles: `urbanev_vehicletypes.xml` → archetype → counterfactual mpg lookup

Annualization:
- Simulation = one typical weekday → VMT_sim_day_weekday
- Annual VMT = `VMT_sim_day_weekday × 252 weekdays + (0.85 × VMT_sim_day_weekday) × 113 weekend/holiday days`
- Equivalent: `≈ VMT_sim_day × 348` (sanity-check against FHWA national LDV avg of 12,000 mi/EV/yr; MD-specific FHWA figure pending — to be sourced from MDOT in Phase 4)

**Counterfactual mpg lookup: PER-EV-TYPE, not per archetype family.**

The fleet has **57 specific EV type names** in
`Input/vehicles/urbanev_vehicletypes.xml` (56 in the lookup CSV; one type is
absorbed into the catch-all `other_bev_mainstream` bucket). Each maps to a
direct counterfactual ICE model. **Built and saved as
`analysis/ev_counterfactual_mpg_lookup.csv`** (last updated 2026-06-07):
56 rows; status="verified" for **49 rows covering 93.34% of the 99,132-vehicle
fleet** (including all top-10 frequencies: model_y 16.4%, model_3 8.2%,
cybertruck 4.1%, ix_i4_i5_i7 4.1%, rav4_prime 3.2%, x5_x3_330e_530e 3.1%,
mustang_mach_e 3.0%, lyriq 3.0%, r1s 3.0%, eqs_eqe_eqb 2.9%);
status="pending" for **8 long-tail rows (6.66% of fleet)** covering
nx_rx_phev, model_x, grand_cherokee_4xe, rz, solterra, sierra_ev, cooper_se,
and i_pace, with proposed counterfactual ICE model + fueleconomy.gov URL
stubs ready for completion in Phase 4 enrichment.

Columns:

```
ev_type, ev_battery_kwh, ev_consumption_kwh_per_100km, ev_mpge,
counterfactual_ice_make_model_year, counterfactual_ice_mpg_combined,
source_url, retrieval_date, notes
```

**Mapping rules:**
- **Direct sibling exists** (Ford F-150 Lightning ↔ Ford F-150 V6, Volvo XC40
  Recharge ↔ Volvo XC40 B5) — use the gas variant directly; cleanest case
- **Segment-equivalent ICE** (Tesla Model Y → Toyota RAV4 LE 2024, Chevy Blazer
  EV → Chevy Blazer gas 2024) — match size class + price tier + body style
- **PHEV** — gasoline portion still incurs gas tax. Tax DISPLACED per PHEV
  agent = `(utilityFactor × VMT / ice_mpg) × $0.466`, where `utilityFactor` is
  the per-agent electric-share attribute from plans XML. The CSV records the
  PHEV's own gas-mode mpg (closer to its hybrid efficiency) — but the
  displacement formula uses `utilityFactor` as the scaling, NOT mpg-replacement
  logic
- All values from EPA fueleconomy.gov (authoritative; cited per row with URL +
  retrieval date)

Output table `analysis/shadow_tax_gap_per_agent.csv`:
```
person_id, sim_vmt_m, sim_vmt_mi, annual_vmt_mi, archetype, mpg_counterfactual,
gallons_displaced_yr, state_tax_displaced_yr_usd, income_decile
```

Fleet-wide:
```
ShadowTaxGap_total = Σ state_tax_displaced_yr_usd
```

### Sanity bound (flat-fleet proxy, for sense-check only)

| Variable | Value | Source / assumption |
| --- | --- | --- |
| MD EV fleet (passenger BEV+PHEV) | ~100,000 | verify with MDOT MVA Q1-2026 registration |
| Avg miles/year per EV | 12,000 | FHWA Highway Statistics nat. avg |
| Avg fuel economy of displaced ICE | 25 mpg | EPA fleet avg, gasoline LDV |
| Gallons displaced per EV-year | 480 gal | 12,000 / 25 |
| MD state tax per gallon | $0.466 | post-Jul 2026 |
| Per-EV annual state-tax loss (flat proxy) | $223.68 | $0.466 × 480 |
| **Fleet-wide flat-proxy bound** | **~$22.4M** | $223.68 × 100,000 |

The simulation-derived total will be near this if MATSim VMT × archetype mpg
mix tracks FHWA + EPA averages — but the simulation number is the load-bearing
one. Any divergence is informative (e.g., simulated VMT below FHWA = MD EV
adopters drive less than the national average, possibly because they skew
urban/dense; this would *reduce* the recovery requirement and reshape Phase 7
scenarios). **A divergence > 25% between sim and flat-proxy is a calibration
flag, not a bug.**

### Phase 7 script: `analysis/compute_shadow_tax_gap.py`

Skeleton (to be written in Phase 7):
```python
import pandas as pd, gzip, xml.etree.ElementTree as ET
from collections import defaultdict

def compute_shadow_gap(output_dir, vehicle_types_xml, mpg_lookup):
    # 1. Load network link lengths
    # 2. Stream events.xml.gz, accumulate distance per personId
    # 3. Annualize: sim_day_mi × 348 (weekday-weighted)
    # 4. Join with person.attributes (income decile, archetype) and vehicletypes (archetype → mpg)
    # 5. Compute per-agent tax displaced; emit CSV
    # 6. Aggregate, return total + per-decile breakdown
```

---

## 3. Per-kWh surcharge sweep design (for Phase 7)

**Per-agent kWh basis (preferred, parallel to per-agent VMT):**
From the same event stream, sum delivered energy per agent via
`ChargingBehaviourScoringEvent` (which already carries `energy_kWh`). Annualize
identically (× 348 weekday-weighted). Per-agent revenue under surcharge =
`annual_kWh_agent × surcharge_$/kWh`. Aggregate over agents.

Sanity-bound assumption (flat-fleet, for the table below only):
mean MD EV uses **~3,600 kWh/yr** (12,000 mi × 0.30 kWh/mi @ EPA-adjusted
wall-to-wheels efficiency including charging losses).

**Derivation check against the per-EV-type CSV:** the lookup table's
`ev_consumption_kwh_per_100km` column gives EPA-rated consumption per type.
Top-10 fleet shares yield ~0.28-0.32 kWh/mi when converted via
`(kWh/100km) ÷ 62.137 mi/100km`. Examples: Model Y 17.4 kWh/100km = 0.280
kWh/mi; Model 3 15.5 = 0.249; Cybertruck 30.4 = 0.489; F-150 Lightning 29.8 =
0.480; iX/i4 19.9 = 0.320; Mach-E 19.9 = 0.320. Fleet-weighted mean
≈ 0.29-0.31 kWh/mi → the 0.30 anchor is consistent with the CSV to within
~5%. PHEV inclusion (~25% of fleet) pulls the dispenser-input mean down
slightly because PHEV electric-mode kWh is multiplied by per-agent
utilityFactor; that effect is captured at per-agent computation time, not in
this sanity bound.

| Surcharge | Per-EV/yr revenue | Fleet-wide/yr |
| --- | --- | --- |
| 0¢/kWh | $0 | $0 |
| 1¢/kWh | $36 | $3.6M |
| 2¢/kWh | $72 | $7.2M |
| 3¢/kWh | $108 | $10.8M |
| **5¢/kWh** | **$180** | **$18.0M** | ← near target if applied to all kWh
| **6¢/kWh** | **$216** | **$21.6M** | ← matches gap if uniform
| 7¢/kWh | $252 | $25.2M |

If applied only to **public charging** (assume 30% of kWh comes from public per EVWatts national avg), the per-kWh rate must scale: ~20¢/kWh public-only surcharge to reach $21.6M.

**Phase 7 sweep grid (24 cells):**
- Surcharge: {0, 1, 3, 5, 7} ¢/kWh
- TOU multiplier shape: {flat, BGE-RL-like, SMECO-aggressive}
- Distribution: {all-kWh, public-only, DCFC-only, public-L2-exempt}
Compute: revenue, equity (by income decile), modal shift (L2 / DCFC), peak-hour grid stress, agent disutility.

---

## 4. Value of Time anchor (for `betaMoney` calibration sanity)

**USDOT 2023 guidance:** $18.80 / hr for personal automobile commute travel-time savings.
**Source:** https://www.transportation.gov/office-policy/transportation-policy/revised-departmental-guidance-valuation-travel-time-economic

**Per-agent VOT** in Maryland plans XML ranges $15–$22/hr (income-stratified), bracketing the USDOT $18.80 median — consistent and authoritative.

**β_money derivation already done in plans:** `betaMoney_i = β_trav,car / VOT_i`. Use as authoritative per-agent value; config-level `params.betaMoney` is fallback only.

---

## 5. Caveats

- 100K MD EV count needs verification with MDOT MVA Q1-2026 registration report (not yet sourced). If actual is materially different, all revenue numbers scale linearly.
- 25 mpg displaced-vehicle FE is conservative; if displaced ICE is heavier (SUV/truck, 22 mpg), gap grows ~14%.
- 12,000 mi/yr is FHWA national avg; MD-specific VMT may differ (MDOT publishes annually).
- Phase 7 will refine all three with MD-specific sources.
