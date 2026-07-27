# Fleet EPA Label Utility Factor — Derivation (2026-07-27)

**Result: sales-weighted EPA label utility factor of the simulated PHEV fleet = 0.606 (report as 0.61).**

## Why this exists
The plans builder (`06_build_plans.py`) hard-codes `utilityFactor = 0.58` for PHEVs (used in the
R* counterfactual), and the paper compared the emergent UF (0.50–0.59) to an "EPA rated 0.58"
with no source. This note replaces that unsourced constant with a derived, citable benchmark.

## Method
1. EPA vehicle database (`vehicles.csv`, fueleconomy.gov/feg/epadata/vehicles.csv.zip,
   downloaded 2026-07-27) — contains per-vehicle `combinedUF`, the label utility factor EPA
   computes per 40 CFR 600.116-12 (SAE J2841 §6.2, Table 2 MDIUF coefficients, norm. distance
   399 mi). Using the published field avoids reproducing the paywalled J2841 coefficients.
2. Filter: atvType = "Plug-in Hybrid", model years 2022–2025, combinedUF > 0.
3. Match each of the 21 PHEV archetypes in `ev_counterfactual_mpg_lookup.csv` to its EPA
   model rows (newest year per member model; family archetypes = mean over members).
   20/21 matched = 99% of PHEV fleet share; `other_phev_mainstream` (0.37 share) proxied by
   the matched share-weighted mean.
4. Weight by `fleet_share_pct`. Full per-archetype table: `phev_epa_label_uf_derivation.csv`.

Hand check: Σ(share×UF) = 15.857, Σshare = 26.18 → 0.6057. (An intermediate run reporting
0.570 was wrong: the unmatched Mercedes row was excluded from the numerator only.)

## Range across archetypes
0.443 (Range Rover PHEV) to 0.743 (MB GLE/GLC/S-class); volume models: RAV4 Prime 0.693,
Prius Prime 0.694, BMW family 0.526, Wrangler 4xe 0.487.

## Implications
- **Paper comparison**: emergent simulated UF 0.50–0.59 sits slightly BELOW the 0.61 label
  benchmark — the direction real-world studies consistently find (real-world PHEV UFs
  undershoot label values), so the comparison is stronger, not weaker.
- **R\* sensitivity**: R* uses the 0.58 constant for PHEV counterfactuals. Using 0.606 would
  raise the PHEV component ~4.5%, i.e. R* by ~0.8% (≈ +$0.3M). Documented, not rerun: well
  below the differences any conclusion rests on, and R* is stated as an upper-bound fiscal
  target with ratio-based rankings.

## Citations
- 40 CFR § 600.116-12 (UF = SAE J2841 §6.2, MDIUF, 399 mi) — ecfr.gov
- SAE J2841_201009, Utility Factor Definitions for PHEVs Using Travel Survey Data
- U.S. DOE/EPA fueleconomy.gov vehicle database (combinedUF field), retrieved 2026-07-27
