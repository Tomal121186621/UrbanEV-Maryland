# Maryland Residential / EV Time-of-Use Tariffs — 2026

**Retrieved:** 2026-06-07
**Purpose:** Source the TOU multipliers used in `ChargingCostUtils.java` (replaces Parishwad's hard-coded Nord Pool SE3 array) and the per-utility "home charging" unit price in the 5-way scoring switch.

**Service-territory assignment plan:** assign each agent's `homeChargerPower` charging-session to one of the four utility tariffs based on the agent's home-activity coordinate intersected with the utility service-territory polygon (cleaner than population-weighted average).

---

## 1. BGE — Baltimore Gas & Electric (≈Baltimore metro + central MD)

| Schedule | Period | $/kWh | Window | Notes |
| --- | --- | --- | --- | --- |
| Schedule R (flat residential) | all hours | **~$0.151** | — | "all-in" effective rate as of Feb 2026 |
| Schedule RL (whole-house TOU) | off-peak | **$0.132** | nights/weekends | |
| Schedule RL (whole-house TOU) | on-peak | **$0.164** | weekday peak | |
| Rider 6 — VC-TOU (EV-only sub-meter) | admin charge | **+$0.00247** | all hours | Effective 06/01/2024; layered on Schedule R |

**Source URLs:**
- https://www.bge.com/MyAccount/MyBillUsage/Pages/ElectricServiceRatesTariffs.aspx
- https://www.bge.com/SmartEnergy/InnovationTechnology/Pages/EVTOURate-TC.aspx (JS-only; page exists but content not fetchable headless — needs human verification of Rider 6 on-peak vs off-peak $/kWh)
- https://utilitycheck.co/utilities/bge (corroborating Feb 2026 effective rate)

**Gap:** BGE Rider 6 (VC-TOU) on-peak / off-peak / super-off-peak $/kWh splits not extractable from headless fetch. **Action:** treat BGE = Schedule RL TOU for now ($0.132 off / $0.164 peak); refine Rider 6 in calibration pass.

---

## 2. Pepco MD — R-PIV (Plug-in Vehicle TOU rate)

| Season | Period | $/kWh | Window |
| --- | --- | --- | --- |
| Summer (Jun–Oct) | off-peak | **$0.2415** | all hours outside 12pm–8pm M–F; all weekend |
| Summer (Jun–Oct) | on-peak | **$0.3550** | 12:00 PM – 8:00 PM, M–F (excluding holidays) |
| Winter (Nov–May) | off-peak | **$0.2015** | as above |
| Winter (Nov–May) | on-peak | **$0.3573** | as above |

**Source URL:** https://pepco.upgrade.guide/ev/ev1/tou/

**Note:** R-PIV is a whole-house TOU plan marketed to EV drivers; comparable to BGE Schedule RL. No shoulder period; no effective-date on the page (live calculator). Tariff is current as of retrieval 2026-06-07.

---

## 3. Delmarva Power MD — R-PIV (Plug-in Vehicle TOU rate)

| Season | Period | $/kWh | Window |
| --- | --- | --- | --- |
| Summer (Jun–Sep) | off-peak (weekday) | **$0.204128** | outside peak window |
| Summer (Jun–Sep) | on-peak | **$0.317445** | 12:00 PM – 8:00 PM, M–F (excluding holidays) |
| Summer | weekend (all hrs) | **$0.241556** | Sat/Sun |
| Winter (Oct–May) | off-peak | **$0.198736** | outside peak window |
| Winter (Oct–May) | on-peak | **$0.358646** | 12:00 PM – 8:00 PM, M–F (excluding holidays) |
| Winter | weekend (all hrs) | **$0.198736** | Sat/Sun |

**Source URL:** https://delmarva.upgrade.guide/ev/ev1/tou/

---

## 4. SMECO — Southern Maryland Electric Cooperative — Schedule TOU

| Season | Period | $/kWh | Window |
| --- | --- | --- | --- |
| Summer (May–Sep) | off-peak | **$0.07681** | outside peak; weekends |
| Summer (May–Sep) | on-peak | **$0.20683** | 2:00 PM – 7:00 PM, M–F |
| Winter (Oct–Apr) | off-peak | **$0.08623** | outside peak; weekends |
| Winter (Oct–Apr) | on-peak | **$0.19531** | 6–9 AM and 5–8 PM, M–F (split-peak) |

**Effective date:** June 1, 2025.
**Source URL:** https://www.smeco.coop/my-account/general-information/rates-fees/time-of-use-rates/

**Note:** SMECO has the *most aggressive* TOU spread (off-peak $0.077 vs peak $0.207 summer → ratio 2.69×). This is the strongest price signal among the four utilities and will be the largest behavioral lever in the scoring.

---

## 5. Hourly TOU table for `ChargingCostUtils.getHourlyCostMultiplier(hourOfDay, utilityId)`

To be implemented as 24-hr arrays indexed [0..23], per utility, per season. The multiplier is computed as `rate_at_hour / mean_rate` so it slots into the existing `unitPricePerKWh × multiplier` pattern in `ChargingBehaviourScoring`. Concrete arrays will be produced in Phase 0.9 / Phase 3.7 as part of the Java edit.

Example (Pepco summer): hours 12–19 → 1.47×; hours 0–11, 20–23 + all weekend → 1.00× (off-peak baseline).
Example (SMECO summer): hours 14–18 → 2.69×; else 1.00×.

---

## 6. Notes & caveats

- BGE rider EV TOU page is JS-rendered; the Rider 6 admin charge (+0.247¢/kWh) is the only confirmed numeric. Recommend treating BGE home-charging as Schedule RL TOU ($0.132 / $0.164) until human-verified Rider 6 peak/off-peak rates are confirmed.
- Pepco / Delmarva R-PIV pages do not list an effective date in headless-extractable form. Both are live rate-calculator pages, so rates are presumed current as of retrieval 2026-06-07. Refine with PSC tariff filings if a published effective date is required.
- "Holiday" exclusion handling will be deferred — MATSim simulation week is a typical weekday cycle; holidays not modeled.
