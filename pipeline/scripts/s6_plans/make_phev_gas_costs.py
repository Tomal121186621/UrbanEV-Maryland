#!/usr/bin/env python3
"""Build research/phev_gas_fallback_costs.csv — per-archetype gasoline cost per kWh of
battery deficit for the PHEV charge-sustaining fallback:
    cost_per_kwh = fuel_price[$ / gal] / cs_mpg[mi / gal] / (kWh / mi)
where cs_mpg is the EPA "Gas Only" (charge-sustaining) combined rating (fueleconomy.gov,
verified 2026-07-16) and kWh/mi comes from the archetype's consumption in
ev_counterfactual_mpg_lookup.csv (kWh/100km / 62.137). Premium-fuel buckets use the AAA MD
premium price; everything else regular (AAA MD, 2026-07-16: reg 3.881 / prem 4.805)."""
import pandas as pd
from pathlib import Path

ROOT = Path("/home/tomal/Documents/UrbanEV_Final_TRB/UrbanEV_Final_TRB")
GAS_REG, GAS_PREM = 3.881, 4.805     # AAA MD state avg, 2026-07-16, gasprices.aaa.com/?state=MD

# EPA charge-sustaining ("Gas Only") combined mpg — fueleconomy.gov, retrieved 2026-07-16
CS_MPG = {
 "rav4_prime": (38, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47502"),
 "x5_x3_330e_530e": (22, "https://www.fueleconomy.gov/feg/bymodel/2025_BMW_X5.shtml"),
 "prius_prime": (52, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47501"),
 "wrangler_4xe": (20, "https://www.fueleconomy.gov/feg/noframes/47278.shtml"),
 "nx_rx_phev": (36, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47498"),
 "xc60_s60_s90_phev": (28, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47504"),
 "grand_cherokee_4xe": (23, "https://www.fueleconomy.gov/feg/noframes/47277.shtml"),
 "gle_glc_s_class_phev": (25, "https://www.fueleconomy.gov/feg/bymodel/2025_Mercedes-Benz_GLC-Class.shtml"),
 "outlander_phev": (26, "https://www.fueleconomy.gov/FEG/noframes/47499.shtml"),
 "cayenne_panamera_phev": (22, "https://www.fueleconomy.gov/feg/bymodel/2025_Porsche_Cayenne.shtml"),
 "pacifica_hybrid": (30, "https://fueleconomy.gov/feg/noframes/47276.shtml"),
 "escape_phev": (40, "https://www.fueleconomy.gov/Feg/noframes/47220.shtml"),
 "aviator_corsair_phev": (33, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47226"),
 "range_rover_phev": (21, "https://www.fueleconomy.gov/feg/bymodel/2025_Land_Rover_Range_Rover.shtml"),
 "q5_e": (26, "https://www.fueleconomy.gov/feg/byfuel/Plug-inHybrid2023.shtml"),
 "sportage_phev": (35, "https://www.fueleconomy.gov/feg/byfuel/Plug-inHybrid2024.shtml"),
 "sorento_phev": (34, "https://www.fueleconomy.gov/feg/byfuel/Plug-inHybrid2024.shtml"),
 "santa_fe_phev": (33, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=46250"),
 "cx_90_phev": (25, "https://www.fueleconomy.gov/feg/bymodel/2024_Mazda_CX-90.shtml"),
 "tucson_phev": (35, "https://www.fueleconomy.gov/feg/Find.do?action=sbs&id=47495"),
 "other_phev_mainstream": (38, "https://www.fueleconomy.gov/feg/bymodel/2024_Toyota_RAV4_Prime.shtml"),
}
PREMIUM = {"x5_x3_330e_530e", "gle_glc_s_class_phev", "cayenne_panamera_phev",
           "xc60_s60_s90_phev", "range_rover_phev", "q5_e"}

look = pd.read_csv(ROOT/"research/ev_counterfactual_mpg_lookup.csv")
phev = look[look.powertrain.str.upper() == "PHEV"].copy()
rows = []
for _, r in phev.iterrows():
    t = r.ev_type
    if t not in CS_MPG:
        raise SystemExit(f"missing CS mpg for {t}")
    mpg, url = CS_MPG[t]
    kwh_per_mi = r.ev_consumption_kwh_per_100km / 62.137
    price = GAS_PREM if t in PREMIUM else GAS_REG
    cost = price / mpg / kwh_per_mi
    rows.append(dict(ev_type=t, cs_mpg=mpg, fuel=("premium" if t in PREMIUM else "regular"),
                     fuel_price_usd_gal=price, kwh_per_mi=round(kwh_per_mi, 4),
                     gas_cost_per_kwh=round(cost, 4), fleet_count=r.fleet_count,
                     source_epa=url))
df = pd.DataFrame(rows).sort_values("fleet_count", ascending=False)
out = ROOT/"research/phev_gas_fallback_costs.csv"
df.to_csv(out, index=False)
w = (df.gas_cost_per_kwh * df.fleet_count).sum() / df.fleet_count.sum()
print(df[["ev_type","cs_mpg","fuel","kwh_per_mi","gas_cost_per_kwh"]].to_string(index=False))
print(f"\nfleet-weighted mean gas cost per kWh deficit: ${w:.3f}")
print(f"-> {out}")
