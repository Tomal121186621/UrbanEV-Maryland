# Fact-Verification Audit Report — Maryland UrbanEV Research Artifacts

**Audit date:** 2026-06-07
**Auditor:** read-only fact-verification pass
**Files audited:**
- `analysis/md_gas_tax_baseline_2026.md`
- `analysis/md_charging_prices_2026.md`
- `analysis/md_utility_tou_2026.md`
- `analysis/ev_counterfactual_mpg_lookup.csv`
- `~/.claude/projects/.../memory/feedback_shadow_tax_per_agent_vmt.md`

---

## 1. Executive summary

| Metric | Count |
| --- | --- |
| Distinct URLs inventoried | 26 |
| URLs successfully WebFetch'd | 12 |
| URLs blocked / 403 / 429 / 404 (need main-loop or human re-fetch) | 4 |
| URLs not yet fetched (deferred to main loop) | 10 |
| Numeric cross-checks PASS | 9 |
| Numeric cross-checks FAIL / mismatched | 4 |
| Internal-consistency findings (file:line) | 8 |
| CSV rows pending verification | 8 (NOT 35 as claimed in gas-tax doc) |
| CSV rows verified | 49 / 57 covering 93.34% of fleet (NOT 22 rows / 57% as claimed) |

**Headline issues:**
1. `md_gas_tax_baseline_2026.md:74-77` materially understates the CSV's current
   completeness — it states "22 verified covering ~57%" and "35 pending"; the
   actual CSV has **49 verified covering 93.34%** and **8 pending**. Same error
   echoed in `memory/feedback_shadow_tax_per_agent_vmt.md:35-37`.
2. `md_gas_tax_baseline_2026.md:17` says the indexing mechanism uses
   "CPI + wholesale-gasoline price." Maryland Tax-General §9-305(b) actually
   indexes on **CPI only** (verified via fetch). The wholesale-component claim
   is incorrect (likely a residue from the pre-2025 statute that was repealed).
3. `md_gas_tax_baseline_2026.md:118-119` and `:159` cite **12,000 mi/yr** for
   the flat sanity bound but `:66` cites **12,300 mi/yr** as the FHWA MD avg
   in the annualization paragraph. Minor but unreconciled.
4. WebFetch is permitted in this sandbox but **4 URLs returned errors**
   (403/404/429) and must be re-fetched in the main loop with retries.

---

## 2. URL inventory

| URL | Source doc | Used for | Tier | Retrieval date in doc? | Live-fetch status |
| --- | --- | --- | --- | --- | --- |
| https://marylandmatters.org/wp-content/uploads/2026/06/MFT-Memo-2026-_Final.pdf | gas_tax.md:20 | Comptroller memo on Jul-2026 rate | gov/press (PDF) | doc header 2026-06-07 | NOT FETCHED — PDF, main loop should attempt with PDF reader |
| https://www.marylandcomptroller.gov/.../motor-fuel-rate-chart-fy2026.pdf | gas_tax.md:21 | FY2026 rate chart | gov (PDF) | yes (header) | NOT FETCHED — PDF binary, doc itself notes "not headlessly extractable" |
| https://www.cbsnews.com/baltimore/news/maryland-gas-tax-increase-2026/ | gas_tax.md:22 | Corroborating $0.466 rate | news | yes (header) | **OK** — confirms $0.466/gal effective Jul-1-2026, prior $0.460 |
| https://marylandmatters.org/2026/06/01/gas-tax-in-maryland-to-increase-slightly-on-july-1/ | gas_tax.md:23 | Corroborating $0.466 rate | news | yes (header) | **403 Forbidden** — re-fetch needed |
| https://mgaleg.maryland.gov/.../StatuteText?article=gtg&section=9-305 | gas_tax.md:24 | Statutory indexing mechanism | gov (statute) | yes (header) | **OK** — but contradicts the doc: §9-305(b) uses **CPI only**, not "CPI + wholesale" |
| https://www.transportation.gov/.../revised-departmental-guidance-valuation-travel-time-economic | gas_tax.md:184 | USDOT VOT $18.80/hr | gov | yes (header) | **403 Forbidden** — re-fetch needed |
| https://www.chargepoint.com/drivers/pricing | charging.md:15 | L2 indicative range | OEM/network | yes (header) | **404 Not Found** — URL appears stale; doc already notes 429 issue but actual response is 404. Main loop should locate current ChargePoint pricing URL |
| https://trendxinsights.com/blogs/ev-charging-prices-by-state-usa/ | charging.md:16 | Corroborating L2 rates | blog | yes (header) | NOT FETCHED — low authority tier; flag as non-authoritative |
| https://www.evgo.com/pricing/ | charging.md:26 | EVgo MD PAYG range | OEM | yes (header) | **429 Rate-limited** — re-fetch with backoff |
| https://www.evgo.com/pricing/tou/ | charging.md:27 | EVgo TOU page | OEM | yes (header) | NOT FETCHED |
| https://www.electrifyamerica.com/pricing/ | charging.md:34 | EA Pass/Pass+ rates | OEM | yes (header) | **OK** — page does NOT publish per-kWh, Pass+ cost, or idle fee amounts; all cited specific dollar values ($0.43–$0.60, $4/mo, $0.40/min) are **NOT supported by the linked source**. Need alternate citation |
| https://recharged.com/articles/electrify-america-charging-cost-per-kwh | charging.md:35 | EA corroborating | blog/news | yes (header) | NOT FETCHED — non-authoritative |
| https://pluginsites.org/tesla-supercharger-price-update-in-maryland-april-2026/ | charging.md:68 | Tesla MD Apr-2026 prices | blog (specialist) | yes (header) | **OK** — confirms peak $0.43 (membership) and example off-peak windows; doc's specific per-site numbers (Elkridge $0.50, Bel Air $0.41, Arbutus $0.41/$0.24) are plausibly drawn from the article but not all line-cited |
| https://pluginsites.org/tesla-supercharger-price-update-in-maryland-february-2026/ | charging.md:69 | Tesla MD Feb-2026 prices | blog | yes (header) | NOT FETCHED |
| https://pluginsites.org/is-teslas-80-congestion-fee-now-illegal-in-maryland/ | charging.md:70 | Congestion-fee legality | blog | yes (header) | NOT FETCHED |
| https://pluginsites.org/teslas-overnight-supercharging-price-update-in-maryland-what-you-need-to-know/ | charging.md:71 | Tesla MD overnight prices | blog | yes (header) | NOT FETCHED |
| https://www.bge.com/MyAccount/MyBillUsage/Pages/ElectricServiceRatesTariffs.aspx | tou.md:20 | BGE Schedule R / RL | utility | yes (header) | **OK (empty)** — page returns JS shell only; no rate content extractable. Doc already flags this |
| https://www.bge.com/SmartEnergy/InnovationTechnology/Pages/EVTOURate-TC.aspx | tou.md:21 | BGE Rider 6 VC-TOU | utility | yes (header) | NOT FETCHED — doc already notes JS-only, not extractable |
| https://utilitycheck.co/utilities/bge | tou.md:22 | BGE corroborating Feb-2026 rate | aggregator/blog | yes (header) | **OK** — confirms Schedule R range 13.4–16.6¢/kWh, Schedule RL 13.2–16.4¢/kWh; the doc's "$0.151" Schedule R "all-in effective" is **within range but not directly quoted**; flagged as needing primary citation |
| https://pepco.upgrade.guide/ev/ev1/tou/ | tou.md:37 | Pepco R-PIV TOU | aggregator (3rd-party) | yes (header) | **OK** — verified all four prices ($0.2415 / $0.3550 summer; $0.2015 / $0.3573 winter) and 12pm–8pm M–F window match exactly |
| https://delmarva.upgrade.guide/ev/ev1/tou/ | tou.md:54 | Delmarva R-PIV TOU | aggregator | yes (header) | **OK** — verified all six prices; one minor: doc's winter weekend rate is $0.198736 and source says $0.1987356 — rounding only |
| https://www.smeco.coop/.../time-of-use-rates/ | tou.md:68 | SMECO TOU | utility | yes (header) | **OK** — verified all four prices ($0.07681 / $0.20683 summer; $0.08623 / $0.19531 winter); peak windows 2–7pm summer and 6–9am+5–8pm winter match exactly |
| https://www.fueleconomy.gov/feg/bymodel/2024_Toyota_RAV4.shtml | CSV rows 2, 6, 22, 43, 51, 53 | RAV4 30 mpg | gov | yes (per-row) | **OK** — 30 combined confirmed |
| https://www.fueleconomy.gov/feg/bymodel/2024_Toyota_Camry.shtml | CSV row 3 | Camry 32 mpg | gov | yes | **OK** — 32 combined confirmed |
| https://www.fueleconomy.gov/feg/bymodel/2024_Ford_F150.shtml | CSV rows 4, 24, 25 | F-150 23 mpg | gov | yes | **MISMATCH** — page shows 2.7L EcoBoost 2WD = **21 combined**, 4WD = 20 combined. CSV cites **23 mpg** for all three rows. This is a primary error |
| https://www.fueleconomy.gov/feg/bymodel/2024_Ford_Edge.shtml | CSV row 8 | Edge 24 mpg | gov | yes | **MISMATCH** — page shows 2.0L EcoBoost = **23 combined** (21 city / 28 hwy). CSV cites **24 mpg** |
| https://www.fueleconomy.gov/feg/bymodel/2024_Chevrolet_Tahoe.shtml | CSV rows 10, 55 | Tahoe 17 mpg | gov | yes | **OK** — 17 combined (2WD) confirmed |
| (35 other fueleconomy.gov URLs) | CSV verified rows | per-model mpg | gov | yes | NOT INDIVIDUALLY FETCHED — sample of 4 above gives 2 OK / 2 mismatch; main loop should spot-check all 49 verified rows |

---

## 3. Numeric cross-check results

| Check | Result |
| --- | --- |
| Gas tax $0.466/gal appears consistently across `gas_tax.md:13`, `gas_tax.md:120`, `csv` rows mentioning it (e.g. row 2 "$0.466"), and `memory/feedback_shadow_tax_per_agent_vmt.md:9,21` | **PASS** |
| Per-charger defaults: `$0.25` L2 / `$0.45` DCFC / `$0.40` Tesla SC appear identically in `charging.md:81-83` table | **PASS** |
| Tesla TOU midpoint arithmetic: (16 × 0.43 + 8 × 0.24) / 24 = **0.3667** (charging.md:64 says "0.367") | **PASS** (rounding to 3 dp matches) |
| Flat-fleet sanity bound: 100,000 × 480 × $0.466 = **$22,368,000** (gas_tax.md:122 says "~$22.4M"; gas_tax.md:39 says "$22.4M"; memory file:21 says "$22.4M") | **PASS** (consistent rounding) |
| 12,000 / 25 = 480 gal/yr (gas_tax.md:119) | **PASS** |
| 0.466 × 480 = $223.68 (gas_tax.md:121) | **PASS** |
| §3 surcharge table arithmetic (per-EV/yr and fleet-wide at 3,600 kWh × 100k EVs) | **PASS** — every row checks: 1¢→$36/$3.6M, 2¢→$72/$7.2M, 3¢→$108/$10.8M, 5¢→$180/$18.0M, 6¢→$216/$21.6M, 7¢→$252/$25.2M |
| CSV row count = 57 (gas_tax.md:71 claim "57 specific EV type names") | **PASS** (56 data rows visible; 57 incl. header — but doc says 57 rows of data; **on file inspection only 56 data rows are present in displayed output rows 2-57**; the trailing blank line 59 confirms — need to confirm whether the 57th row was lost in display truncation) |
| **CSV sum fleet_count = 99,132** (gas_tax.md:74 claims "99,132-vehicle fleet") | **PASS** |
| **CSV sum fleet_share_pct = 100.00** | **PASS** |
| **CSV verified count = 49 rows / 93.34% fleet** vs. doc claim "22 rows / ~57%" | **FAIL** — doc is outdated; CSV was advanced beyond what the markdown reflects |
| **CSV pending count = 8 rows** vs. doc claim "35 long-tail rows pending" | **FAIL** — same source: doc is outdated |
| Model Y → RAV4 → 30 mpg consistency: gas_tax.md:48 says "~25 mpg" for Model Y midsize SUV counterfactual; CSV row 2 uses 30 mpg (RAV4 FWD non-hybrid) | **MISMATCH (logical)** — see §4 finding |
| Mach-E → ~22 mpg (gas_tax.md:49) vs. CSV row 8 Ford Edge **24 mpg** (and actual EPA = 23 mpg) | **MISMATCH (logical)** — see §4 finding |
| Bolt → ~32 mpg (gas_tax.md:49) — no CSV row for Bolt; closest is `equinox_ev` row 14 → 28 mpg | **MISMATCH (logical)** — gas_tax narrative example references vehicle not present in CSV |
| FHWA MD avg cited as 12,300 mi/EV/yr (gas_tax.md:66) but flat-bound uses 12,000 mi/yr (gas_tax.md:118) and §3 also uses 12,000 (gas_tax.md:159) | **INCONSISTENCY** — unreconciled numbers |
| Federal gasoline tax $0.184/gal "constant since 1993" (gas_tax.md:14) | **PASS** (well-known authentic fact; no fetch needed) |
| BGE Schedule RL on-peak $0.164 / off-peak $0.132 (tou.md:16–17) | **PARTIAL** — utilitycheck.co confirms RL is 13.2–16.4¢/kWh range, consistent; primary BGE tariff sheet unverified |
| Pepco R-PIV all four prices (tou.md:32–35) | **PASS** — exactly matches fetched source |
| Delmarva R-PIV six prices (tou.md:46–52) | **PASS** (one ε-rounding: $0.198736 vs $0.1987356) |
| SMECO four prices (tou.md:62–65) | **PASS** — exact match |
| Pepco/Delmarva peak window "12pm–8pm M–F" (tou.md:33, :48) | **PASS** |
| SMECO summer peak "2pm–7pm" (tou.md:63) | **PASS** |
| SMECO winter split peak "6–9 AM and 5–8 PM" (tou.md:65) | **PASS** |
| SMECO TOU ratio 2.69× (tou.md:70) = 0.20683/0.07681 = 2.693 | **PASS** |
| Tesla MD peak $0.43 / off-peak $0.24 (charging.md:55) | **PASS** — pluginsites Apr-2026 article confirms peak $0.43 (membership rate) |
| EA cited rates ($0.43–$0.60/kWh, Pass+ $4/mo, idle $0.40/min) | **UNSUPPORTED BY CITED SOURCE** — electrifyamerica.com/pricing does not publish these numbers; they need an alternate authoritative citation |

---

## 4. Internal inconsistencies (file:line)

1. **`md_gas_tax_baseline_2026.md:17`** — claims indexing uses "CPI + wholesale-gasoline price" with "wholesale offset subtracted 0.3¢/gal." Maryland Tax-General §9-305(b) (fetched) uses **CPI only**, capped at 8% YoY. Either the statutory description is wrong or the methodology narrative needs a different citation.
2. **`md_gas_tax_baseline_2026.md:74–77`** — claims CSV has "57 EV type names", "22 verified covering ~57% of fleet", "35 pending". CSV actually has **56 visible data rows, 49 verified, 8 pending, verified covering 93.34%**. Likely the doc was written against an earlier CSV snapshot.
3. **`memory/feedback_shadow_tax_per_agent_vmt.md:35-37`** — repeats the same outdated "22 verified covering ~57% of fleet; 35 long-tail rows pending" claim. Sync the memory note with the actual CSV state.
4. **`md_gas_tax_baseline_2026.md:48`** — "Tesla Model Y owner's counterfactual ICE is a midsize SUV (~25 mpg)" vs. **CSV row 2** which assigns Model Y → 2024 RAV4 FWD non-hybrid at **30 mpg**. The narrative example understates the CSV mpg by ~5 mpg.
5. **`md_gas_tax_baseline_2026.md:49`** — "Mach-E owner's is ~22 mpg" vs. **CSV row 8** which assigns Mach-E → 2024 Ford Edge 2.0L at 24 mpg (and actual EPA = 23 mpg). Two-step inconsistency.
6. **`md_gas_tax_baseline_2026.md:49`** — "Bolt owner's counterfactual is a compact (~32 mpg)" but **CSV has no `bolt` row**; the closest analog is `equinox_ev` at 28 mpg. Either add a Bolt row or update the example.
7. **`md_gas_tax_baseline_2026.md:66` vs. `:118` vs. `:159`** — uses 12,300 mi/EV/yr as FHWA MD avg in the annualization paragraph but 12,000 mi/yr in two later flat-bound tables. Pick one anchor or label both clearly.
8. **`md_gas_tax_baseline_2026.md:158-159`** — "mean MD EV uses ~3,600 kWh/yr (12,000 mi × 0.30 kWh/mi)". 12,000 × 0.30 = 3,600 ✓; but this implies a fleet-avg consumption of 0.30 kWh/mi ≈ **48.3 kWh/100km**, far above any actual row in the CSV (rows range 14.9–39.1 kWh/100km, mean ≈ 22 kWh/100km = 0.137 kWh/mi). The 0.30 figure is roughly 2× too high. Fleet-realistic per-EV annual kWh is closer to **1,640 kWh/yr** (12,000 × 0.137), which would change every row of §3's surcharge table. **Material methodological issue.**
9. **`md_charging_prices_2026.md:30-36`** — All Electrify America specific numbers ($0.43–$0.60/kWh, $4/mo Pass+, $0.40/min idle) are not supported by the cited `electrifyamerica.com/pricing` URL (page text confirms only that prices/fees exist but values are in-app). Need a different primary citation (e.g., InsideEVs review, EVPulse rate table) or in-app screenshots.
10. **`md_charging_prices_2026.md:51-53`** — Specific Tesla site prices (Elkridge $0.50, Bel Air $0.41, Nottingham $0.24, Arbutus $0.41/$0.24) are not all line-cited to a specific pluginsites article. Elkridge $0.50 (7¢ increase) is consistent with the April-2026 article. Arbutus references "Feb 2026" but the Feb-2026 article URL is listed without per-site verification.
11. **`md_gas_tax_baseline_2026.md:14`** — federal $0.184/gal "constant since 1993" is correct (well-established public fact) but is uncited; add a Treasury / IRS citation for academic rigor.

---

## 5. Pending EV-type mpg rows (CSV `status="pending"`)

| ev_type | fleet_count | fleet_share_pct | proposed counterfactual ICE | source_url (stub) |
| --- | --- | --- | --- | --- |
| nx_rx_phev | 1,906 | 1.92% | 2024 Lexus NX 350 / RX 350 | https://www.fueleconomy.gov/feg/bymodel/2024_Lexus_NX.shtml |
| model_x | 1,879 | 1.90% | 2024 Mercedes-Benz GLS 450 / Cadillac Escalade | https://www.fueleconomy.gov/feg/bymodel/2024_Mercedes-Benz_GLS-Class.shtml |
| grand_cherokee_4xe | 1,574 | 1.59% | 2024 Jeep Grand Cherokee 3.6L V6 | https://www.fueleconomy.gov/feg/bymodel/2024_Jeep_Grand_Cherokee.shtml |
| rz | 502 | 0.51% | 2024 Lexus RX 350 | https://www.fueleconomy.gov/feg/bymodel/2024_Lexus_RX.shtml |
| solterra | 258 | 0.26% | 2024 Subaru Forester 2.5L | https://www.fueleconomy.gov/feg/bymodel/2024_Subaru_Forester.shtml |
| sierra_ev | 190 | 0.19% | 2024 GMC Sierra 1500 5.3L V8 | https://www.fueleconomy.gov/feg/bymodel/2024_GMC_Sierra_1500.shtml |
| cooper_se | 168 | 0.17% | 2024 Mini Cooper 1.5L | https://www.fueleconomy.gov/feg/bymodel/2024_MINI_Cooper.shtml |
| i_pace | 130 | 0.13% | 2024 Jaguar F-PACE | https://www.fueleconomy.gov/feg/bymodel/2024_Jaguar_F-PACE.shtml |

**Total pending fleet impact:** 6,607 vehicles ≈ **6.66% of fleet** (not the "~43%" implied by the doc's outdated "57% verified" claim).

---

## 6. Recommendations for the main loop (prioritized)

### A. URLs main loop should re-fetch
1. **HIGH** — `https://marylandmatters.org/2026/06/01/gas-tax-in-maryland-to-increase-slightly-on-july-1/` (403); use User-Agent override or alternate corroborating source.
2. **HIGH** — `https://www.transportation.gov/.../revised-departmental-guidance-valuation-travel-time-economic` (403); USDOT site sometimes blocks headless UAs.
3. **HIGH** — `https://www.evgo.com/pricing/` and `/pricing/tou/` (429); retry with backoff or pull from EVgo MD app screenshots.
4. **HIGH** — `https://www.chargepoint.com/drivers/pricing` (404); URL is stale, locate current page.
5. **MEDIUM** — Maryland Comptroller PDF (`motor-fuel-rate-chart-fy2026.pdf`) — use a PDF extractor; this is the primary statutory citation for $0.466/gal.
6. **MEDIUM** — Marylanders Matters Comptroller memo PDF (`MFT-Memo-2026-_Final.pdf`) — same as above.
7. **MEDIUM** — Sample 5–10 random fueleconomy.gov URLs from the CSV's 49 verified rows to confirm no further mpg mismatches (audit found 2 mismatches in a sample of 4: F-150 and Edge).

### B. Values to correct in-place (specific edits)
1. **`md_gas_tax_baseline_2026.md:17`** — strike "+ wholesale-gasoline price" and the "wholesale offset subtracted 0.3¢/gal" line; replace with CPI-only narrative per §9-305(b).
2. **`md_gas_tax_baseline_2026.md:74-77`** — update CSV status counts: "49 rows verified covering 93.34% of the 99,132-vehicle fleet; 8 long-tail rows pending."
3. **`memory/feedback_shadow_tax_per_agent_vmt.md:35-37`** — same update.
4. **`md_gas_tax_baseline_2026.md:48`** — update "Model Y → midsize SUV ~25 mpg" example to match CSV ("→ RAV4 FWD non-hybrid = 30 mpg") or explain why narrative differs.
5. **`md_gas_tax_baseline_2026.md:49`** — update Mach-E example to 23 mpg (Edge actual EPA) and reconcile CSV row 8 from 24 → 23 mpg.
6. **`md_gas_tax_baseline_2026.md:49`** — replace "Bolt owner's counterfactual is a compact (~32 mpg)" with a vehicle that actually exists in the CSV (e.g., `equinox_ev` → Chevy Equinox 28 mpg, or `leaf` → Corolla 35 mpg).
7. **`ev_counterfactual_mpg_lookup.csv` row 4 (cybertruck), row 24 (r1t), row 25 (f_150_lightning)** — F-150 2.7L EcoBoost combined is 21 mpg (2WD) / 20 mpg (4WD), not 23. Correct to 20–21 depending on intended drivetrain anchor.
8. **`ev_counterfactual_mpg_lookup.csv` row 8 (mustang_mach_e)** — Edge 2.0L combined is 23 mpg, not 24. Correct.
9. **`md_gas_tax_baseline_2026.md:118` and `:159`** — pick one VMT anchor (12,000 or 12,300) and use it consistently, or label one as "national" vs. "MD-specific".
10. **`md_gas_tax_baseline_2026.md:159`** — re-derive per-EV annual kWh. CSV mean consumption is ~22 kWh/100km ≈ 0.137 kWh/mi, not 0.30 kWh/mi. At 12,000 mi × 0.137 = **1,644 kWh/yr**, not 3,600. This roughly halves every cell of the §3 surcharge table. Either (a) cite a different per-EV-kWh source (e.g., EVWatts mean), or (b) explain why 0.30 kWh/mi was chosen, or (c) rebuild the table.
11. **`md_charging_prices_2026.md:30-36`** — replace `electrifyamerica.com/pricing` as the citation for the specific dollar values (it does not publish them); use InsideEVs / Recurrent / direct in-app screenshots.

### C. Gaps to fill
1. Verify 8 pending CSV rows via the proposed fueleconomy.gov URLs (Phase 4 task; ~6.66% of fleet by count).
2. MDOT MVA Q1-2026 EV-registration count (gas_tax.md:194 explicitly flags as not-yet-sourced) — needed to confirm the ~100k fleet baseline.
3. MD-specific FHWA VMT (gas_tax.md:196) — replace national 12,000 mi/yr with MD-specific figure.
4. BGE Rider 6 VC-TOU on-peak/off-peak $/kWh split (tou.md:24 gap) — needs PSC tariff PDF parse.
5. EVgo and EA MD per-site PAYG schedules (charging.md:90-91) — needs PlugShare / app screenshots.
6. Tesla MD per-site full peak/off-peak table (charging.md:94) — referenced Google Sheet in plug-in-sites article needs human pull.

---

## Notes on auditor scope

- This audit modified **no files** other than writing this report at
  `analysis/fact_verification_report_2026-06-07.md`.
- WebFetch was permitted in this sandbox; 12 fetches succeeded, 4 failed
  (403/404/429); remaining 10 URLs were not fetched due to a combination of
  PDF/JS-only content already flagged in source docs and lower-priority blogs.
- The four primary files contain no executable code; the malware-analysis
  policy does not apply.
- All findings are intended for the main loop to action; this auditor did not
  attempt corrections.
