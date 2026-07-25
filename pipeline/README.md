# UrbanEV-Maryland synthesis pipeline

End-to-end synthetic population → trips → 2026 EV owners → geolocation → MATSim plans.
Everything is organized into separate folders by concern.

```
pipeline/
├── docs/                      reference material
│   ├── burra_cirillo_2024_charging_ev_adoption.pdf   the EV-ownership model paper
│   └── RTS_Public_File_data_dictionary.xlsx          survey codebook
├── src/                       shared modules (importable as `src.*`)
│   ├── cvae.py  encoders.py   plain mixed CVAE + codec
│   ├── trips.py  tripdisc.py  trip day representation (activity-time model)
│   ├── twostage.py            factorized-CVAE negative-result variant
│   ├── labels.py              codebook value labels for figures
│   └── plotstyle.py           publication (TRB) figure style
├── scripts/                   one folder per pipeline STAGE (run in order)
│   ├── s0_clean/              00_clean_survey.py
│   ├── s1_population/         01_train_population_cvae.py, 03_synthesize.py
│   ├── s2_trips/              02e_train_trip_disc.py (production) + 02/02a/02b variants
│   ├── s3_ownership/          04_ev_ownership_cirillo.py  (Lavan/Burra-Cirillo, 2026-calibrated)
│   ├── s4_validation/         07_validate.py, 08/09 model comparisons
│   ├── s5_geolocation/        (coming) OSM-POI activity placement + AFDC charging
│   └── s6_plans/              (coming) MATSim plan builder
├── data/
│   ├── raw/  interim/  geo/   survey, cleaned parquets, tract shapes/centroids
│   ├── chargers/  afdc/       charging-infrastructure covariates
│   └── osm/                   OpenStreetMap POI extract
├── checkpoints/               trained model weights + codecs
└── output/
    ├── validation/            76 TRB-grade figures (A_..H_) + summary
    ├── ev_ownership/  plans/   deliverables
```

Scripts find the repo root at any depth via
`ROOT = next(p for p in Path(__file__).resolve().parents if (p/"pipeline").is_dir())`,
so they run unchanged from their stage subfolder.

## Base year vs target year (2017 → 2026)
The survey (RTS/MTS) and the estimated EV-ownership logit are **2017–2019**; the
simulation target is **2026** (Maryland MVA ≈ 148,359 EVs). The transfer follows the
canonical discrete-choice temporal-transfer procedure (Train 2009 §2.8; Fox & Hess):
1. **2026 covariates** — update exogenous variables to 2026, especially charging
   infrastructure (AFDC L2 ≤1000 m / DCFC ≤5 mi from the tract centroid) and real income.
2. **Sample enumeration** — expected owners = Σ weight × P(EV).
3. **ASC recalibration** — update the constant per county by `α¹ = α⁰ + ln(S/Ŝ)`
   (slopes fixed) so aggregate ownership matches the 2026 MVA registration control.
