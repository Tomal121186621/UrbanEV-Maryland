# UrbanEV-Maryland

A generative agent-based framework for electric-vehicle charging demand and road-funding
policy in Maryland: conditional variational autoencoders (population + activity-travel
synthesis) → registration-calibrated EV ownership → MATSim/UrbanEV charging simulation of
148,302 EV owners on an AADT-congestion-loaded network → shadow gas-tax gap (R*) and
policy-instrument analysis (charging surcharges, registration fees, road-use charges,
corridor tolls) with per-agent incidence.

Maryland Transportation Institute, University of Maryland, College Park.

## Repository layout

```
pipeline/     Python synthesis pipeline (stages s0–s6)
              s0_clean       codebook-driven survey cleaning
              s1_population  plain household CVAE (from scratch, PyTorch)
              s2_trips       conditional trip CVAE with feasibility-constrained decoding
              s3_ownership   Burra–Cirillo binomial logit + per-county MVA calibration
              s4_validation  marginals (TVD), joints (Cramér's V), fleet, model tests
              s5_geolocation OSM POI placement preserving generated trip distances
              s6_plans       MATSim plans + fleet build (06 = EV-only build of record)
simulation/   Java MATSim/UrbanEV extension (Maven project)
              src/           per-agent money scoring, PHEV gas fallback, dwell cost,
                             per-type pricing, road-use excise, roadpricing wiring
              scenarios/     run configs (baseline, policy sweep, TRR UQ/sensitivity)
analysis/     post-run analysis + publication figures (pubfig style)
              policy frontiers, incidence/Suits, diversion, congestion maps,
              validation panels, AADT time-variant network builder (v3)
docs/         research notes (prices, gas-tax baseline, TOU) + verification reports
reference/    small citable lookup tables (EV archetypes/counterfactual mpg, PHEV costs)
```

## Data (not included)

Input data are excluded for size and licensing reasons. To reproduce:

| Data | Source | Used for |
|---|---|---|
| BMC/TPB Regional Travel Survey microdata | Baltimore Metropolitan Council (by request) | CVAE training |
| MDOT MVA EV registrations by county | opendata.maryland.gov | ownership calibration |
| MDOT SHA AADT segments | roads.maryland.gov / SHA open data | congestion loading |
| AFDC station registry | afdc.energy.gov | charger network |
| ChargePoint occupancy panel (May 2026) | collected by the authors (collector in analysis/) | charging validation |
| EPA vehicle specs | fueleconomy.gov (per-row URLs in reference/) | fleet attributes |
| TIGER 2020 MD tracts, OSM Maryland extract | census.gov, geofabrik.de | geolocation, network |

Make/model shares within powertrain are author-estimated from 2025 U.S. sales tracking
(Cox Automotive/KBB, InsideEVs); county×powertrain shares are MVA. See
`docs/reports/MakeModel_Assignment_Report.pdf`.

## Build & run

```bash
# Python pipeline
python -m venv .venv && .venv/bin/pip install torch pandas numpy scipy geopandas matplotlib
.venv/bin/python pipeline/scripts/s0_clean/00_clean_survey.py   # ... stages in order

# Java simulation (JDK 17, Maven)
cd simulation && mvn package -DskipTests -Denforcer.skip=true
java -Xmx20g -cp target/*-jar-with-dependencies.jar se.umd.MdEVMain scenarios/config_gasfb4_baseline_25pct.xml
```

## Key results (converged, seed-replicated)

- Shadow gas-tax gap R* ≈ $33.3M/yr for the 2026 Maryland EV fleet
- Public charging surcharges structurally cannot recover R* (ceiling ≈ 28% of R*)
- Home surcharge crosses R* near +12¢/kWh; least regressive instrument (Suits −0.142)
- Distance-based road-use and corridor charges recover 91–100% of R* and reproduce the
  fuel tax's incidence (Suits −0.175/−0.177 vs −0.176), losing only 4–6% of tolled VMT
  to diversion
- Validation: TVD 0.045 (held-out survey) / 0.070 (ACS); Cramér's V error 0.057;
  ChargePoint occupancy r = 0.78, session starts r = 0.93; emergent PHEV utility factor
  0.50–0.59 vs EPA rated 0.58

## Citation

Tomal, R. S., and C. Cirillo. A Generative Agent-Based Framework for Electric-Vehicle
Charging Demand and Road-Funding Policy. TRB Annual Meeting manuscript, 2026.
