# Maryland Public Charging Network Prices — 2026

**Retrieved:** 2026-06-07
**Purpose:** Source the per-type unit prices `publicL2Cost`, `publicDcfcCost`, `publicDcfcTeslaCost` for the 5-way scoring switch (Phase 3.3).

---

## 1. Public L2 (`charger_types="L2"`) — ChargePoint / Volta / Blink / EVgo L2

**Indicative range (US national, 2026):** $0.20 – $0.40 / kWh at networked public L2; some operators use hourly billing instead.

**NEW 2026 development — ChargePoint Service Fee (effective March 2026):**
ChargePoint now adds a per-session Service Fee on top of the station-owner's $/kWh
rate. For account holders the fee is **$0.25 / session on L2** and **$0.49 /
session on DCFC**. For a typical 25-kWh L2 top-up this raises effective $/kWh by
~$0.01; for a quick 10-kWh L2 visit the effective uplift is ~$0.025/kWh.

**Recommended default for MD public L2:** **$0.25 / kWh** (mid-range; many MD
public L2 sites are ChargePoint commercial-host installs with per-host pricing
that varies). Service Fee will be modeled as a fixed per-session surcharge in
Phase 5 if EVWatts MD post-March-2026 sessions show the uplift.

**Sources:**
- https://www.chargepoint.com/drivers/support/faqs/what-are-pricing-policies-and-fees-i-should-be-aware (ChargePoint FAQ on pricing/fees)
- https://www.evconnect.com/blog/chargepoint-raises-fees-in-2026/ (March 2026 fee change reporting)
- https://recharged.com/articles/chargepoint-charging-cost-per-session (2026 ChargePoint cost guide)
- https://trendxinsights.com/blogs/ev-charging-prices-by-state-usa/ (2026 by-state breakdown; corroborating)
- Note: the legacy https://www.chargepoint.com/drivers/pricing URL is now 404 — replaced with /support/faqs/... URLs above.

**Calibration source (preferred):** EVWatts MD-metro `evse.pricing` aggregated
mean — supersedes nominal posted rates because it reflects what MD drivers
actually paid.

**Calibration source (preferred):** EVWatts MD-metro `evse.pricing` aggregated mean — supersedes nominal posted rates because it reflects what MD drivers actually paid.

---

## 2. Public DCFC (`charger_types="DCFC"`) — EVgo / Electrify America / ChargePoint Express

### EVgo (per-kWh in MD, TOU)
- **PAYG rate (no membership):** $0.34 – $0.50 / kWh, TOU-shaped (Early Bird / Off-Peak / Peak)
- **Source:** https://www.evgo.com/pricing/ — page accessible; specific MD-TOU $/kWh windows visible only in EVgo app
- **TOU page:** https://www.evgo.com/pricing/tou/
- **Recommended MD default:** **$0.42 / kWh** (midpoint; refine with PlugShare MD samples)

### Electrify America
- **Pass (free tier):** ~$0.43 – $0.60 / kWh DCFC, varies by site
- **Pass+ ($4/mo):** ~25% discount, eliminates $1 session fee → ~$0.40s/kWh effective
- **Idle fee:** $0.40/min after grace
- **Source caveat:** EA's primary pricing page (https://www.electrifyamerica.com/pricing/) confirms the product structure (Pass / Pass+ / idle fees) but the specific per-kWh and per-month dollar values are visible only in the EA mobile app per chosen MD location. The numbers above are drawn from third-party rate aggregators (Recurrent, InsideEVs, Recharged) summarizing EA station rates in MD as of Q1-Q2 2026. **Phase 4 action:** capture in-app screenshots at 3+ MD EA stations (e.g., Hagerstown, Frederick, BWI) or supplement with InsideEVs MD-rate-survey citation for primary support.
- **Aggregator references:** https://recharged.com/articles/electrify-america-charging-cost-per-kwh (corroborating)
- **Recommended MD default:** **$0.48 / kWh** (Pass non-member at typical MD 150-kW station); flagged as needing primary in-app verification in Phase 4

### Weighted MD public-DCFC default
With ~50/50 EVgo/EA share of 274 MD DCFC entries (excluding Tesla SC):
- **`publicDcfcCost = 0.45 / kWh`** (weighted midpoint; sensitivity ±10% in Phase 5)

---

## 3. Public DCFC — Tesla Supercharger (`charger_types="DCFC_TESLA"`)

**Updated April 9, 2026, statewide MD price update.**

| Site (example) | Peak $/kWh | Off-peak $/kWh | Peak window |
| --- | --- | --- | --- |
| Elkridge, MD | up to $0.50 (+$0.07 from prior) | varies | 8 AM – 11 PM |
| Bel Air (Tobin Crossing), MD | $0.41 | — | — |
| Nottingham, MD | — | $0.24 (was $0.22) | off-peak: midnight – 8 AM |
| Arbutus, MD (Feb 2026) | $0.41 | $0.24 | peak 8 AM–11 PM, off 11 PM–8 AM |

**Statewide MD average (Apr 2026):** peak ~**$0.43 / kWh**; off-peak ~**$0.24 / kWh**.
**Coverage:** ~75% of MD Tesla SC sites use TOU pricing.

**Idle fee:** $0.50/min (≥50% full), $1.00/min (100% full); grace period applies.
**Congestion fee:** Tesla's 80% congestion fee policy was challenged for MD legality (see Plug-In Sites article); status flagged for review — exclude from scoring v1.

**Tesla membership subscription:** $12.99/mo eliminates non-Tesla surcharge ≈ $0.05–0.10/kWh; assume Tesla vehicles in our fleet (`charger_types` contains `DCFC_TESLA`) are owner-pays-base-rate.

**Recommended scoring defaults:**
- `publicDcfcTeslaCost = 0.40 / kWh` (time-weighted mean of peak/off-peak ≈ 16h peak × $0.43 + 8h off × $0.24 = 0.367 → round to 0.40 to account for site variability)
- Apply MD-specific TOU multipliers (8 AM–11 PM = 1.08×; 11 PM–8 AM = 0.60×) so the time-of-charge gradient is faithful.

**Sources:**
- https://pluginsites.org/tesla-supercharger-price-update-in-maryland-april-2026/
- https://pluginsites.org/tesla-supercharger-price-update-in-maryland-february-2026/
- https://pluginsites.org/is-teslas-80-congestion-fee-now-illegal-in-maryland/
- https://pluginsites.org/teslas-overnight-supercharging-price-update-in-maryland-what-you-need-to-know/

---

## 4. Summary table for `UrbanEVConfigGroup` defaults

| Field | Default ($/kWh) | TOU? | Source authority |
| --- | --- | --- | --- |
| `homeChargingCost` | per-utility (see md_utility_tou_2026.md) | yes | BGE / Pepco / Delmarva / SMECO tariffs |
| `workChargingCost` | 0.00 (employer-provided) by default | no | per-agent `workChargerPower>0` gating already controls; refine in Phase 5 if EVWatts shows non-zero employer-charged rate |
| `publicL2Cost` | **0.25** | no | ChargePoint commercial / network avg (refine from EVWatts MD aggregates) |
| `publicDcfcCost` | **0.45** | optional | EVgo/EA weighted MD midpoint |
| `publicDcfcTeslaCost` | **0.40** | yes (heavy) | Tesla MD time-weighted mean |

**Sensitivity sweep in Phase 5:** ±10% on each, plus pure-TOU vs flat-DCFC comparison.

---

## 5. Outstanding verification (Phase 4 cleanup)

- EVgo MD per-site PAYG schedule — needs PlugShare/app spot-checks at 5+ sites
- Electrify America MD per-site rate — needs in-app screenshots or `ea.com/find-charger` per-station prices
- BGE Rider 6 VC-TOU on-peak vs off-peak $/kWh — needs PSC tariff sheet (PDF parsing failed headlessly)
- Maryland-specific ChargePoint host pricing distribution — needs EVWatts `evse.pricing` aggregation
- Tesla MD per-site peak/off-peak full table — referenced Google Sheet in Plug-In Sites article needs human pull

---

## 5. REVISION 2026-07-17 — free-weighted effective public L2 price (final baseline)

`publicL2Cost = 0.155 $/kWh` = 0.62 x $0.25 (paid ports at ChargePoint host mid-range;
AFDC stated-rate median $0.20 corroborates) + 0.38 x $0 (free ports).
- Free-port share: AFDC MD extract (Mar 1 2026): 415/1,391 public L2 stations (30%)
  explicitly "Free" = 38% of L2 ports.
- Corroboration: EVWatts national evse table — 7,515 of 8,516 designated
  non-residential L2 EVSEs (88%) are pricing="Free" (field is categorical, so the
  earlier "EVWatts actually-paid mean" note in Section 1 was NOT computable; superseded
  by this derivation).
- DCFC/Tesla unchanged (0.43/0.40, Sections 2-3): corridor DCFC usage concentrates on
  paid EA/EVgo networks; free dealership DCFC treated as niche (limitation noted).
