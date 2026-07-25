package se.urbanEV.scoring;

import se.urbanEV.config.UrbanEVConfigGroup;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.api.internal.MatsimParameters;

public class ChargingBehaviourScoringParameters implements MatsimParameters {

    private static final Logger log = Logger.getLogger(ChargingBehaviourScoringParameters.class);

    public final double marginalUtilityOfRangeAnxiety_soc;
    public final double utilityOfEmptyBattery;
    public final double marginalUtilityOfWalking_m;
    public final double utilityOfHomeCharging;
    public final double marginalUtilityOfSocDifference;
    public final double defaultRangeAnxietyThreshold;

    //added spatio-temporal components for charging costs- OmkarP.(2025)
    public final double betaMoney;
    public final double homeChargingCost;
    public final double workChargingCost;
    public final double publicChargingCost;
    // Maryland 5-way per-type public costs (MD fork)
    public final double publicL2Cost;
    public final double publicDcfcCost;
    public final double publicDcfcTeslaCost;
    // MD fork (2026-07): flat EV road-use excise [currency/kWh] + its scope
    public final double roadExcisePerKWh;
    public final String roadExciseScope;   // all | public | dcfc
    public final double alphaScaleCost;   // cost scaling
    public final double defaultHomeChargerPower; // kW
    // MD fork (2026): opportunity cost of charging dwell time [util/s]. Negative.
    public final double chargingTimeUtility_util_per_s;
    // MD fork (2026-07): PHEV gas fallback default [currency/kWh of battery deficit];
    // person attribute phevGasCostPerKwh overrides per agent.
    public final double defaultPhevGasCostPerKwh;

    private ChargingBehaviourScoringParameters(
            final double marginalUtilityOfRangeAnxiety_soc,
            final double utilityOfEmptyBattery,
            final double marginalUtilityOfWalking_m,
            final double utilityOfHomeCharging,
            final double marginalUtilityOfSocDifference,
            final double defaultRangeAnxietyThreshold,
            final double betaMoney,
            final double alphaScaleCost,
            final double defaultHomeChargerPower,
            final double homeChargingCost,
            final double workChargingCost,
            final double publicChargingCost,
            final double publicL2Cost,
            final double publicDcfcCost,
            final double publicDcfcTeslaCost,
            final double roadExcisePerKWh,
            final String roadExciseScope,
            final double chargingTimeUtility_util_per_s,
            final double defaultPhevGasCostPerKwh) {
        this.marginalUtilityOfRangeAnxiety_soc = marginalUtilityOfRangeAnxiety_soc;
        this.utilityOfEmptyBattery = utilityOfEmptyBattery;
        this.marginalUtilityOfWalking_m = marginalUtilityOfWalking_m;
        this.utilityOfHomeCharging = utilityOfHomeCharging;
        this.marginalUtilityOfSocDifference = marginalUtilityOfSocDifference;
        this.defaultRangeAnxietyThreshold = defaultRangeAnxietyThreshold;
        this.betaMoney = betaMoney;
        this.alphaScaleCost = alphaScaleCost;
        this.defaultHomeChargerPower = defaultHomeChargerPower;
        this.homeChargingCost = homeChargingCost;
        this.workChargingCost = workChargingCost;
        this.publicChargingCost = publicChargingCost;
        this.publicL2Cost = publicL2Cost;
        this.publicDcfcCost = publicDcfcCost;
        this.publicDcfcTeslaCost = publicDcfcTeslaCost;
        this.roadExcisePerKWh = roadExcisePerKWh;
        this.roadExciseScope = roadExciseScope;
        this.chargingTimeUtility_util_per_s = chargingTimeUtility_util_per_s;
        this.defaultPhevGasCostPerKwh = defaultPhevGasCostPerKwh;
    }

    /**
     * MD 5-way unit-cost resolver: returns currency-per-kWh for the given charger
     * type. Falls back through (type-specific) → publicChargingCost lump → 0.0.
     * Tesla falls back to DCFC, then public, then 0.0.
     */
    public double resolveUnitCost(String chargerType) {
        if (chargerType == null) return 0.0;
        switch (chargerType) {
            case "home":         return homeChargingCost;
            case "work":         return workChargingCost;
            // MD fork (2026-07): free public L2 (AFDC pricing="Free" stations)
            case "L2F":          return 0.0;
            case "L2":           return publicL2Cost > 0.0 ? publicL2Cost : publicChargingCost;
            case "DCFC":         return publicDcfcCost > 0.0 ? publicDcfcCost : publicChargingCost;
            case "DCFC_TESLA":   return publicDcfcTeslaCost > 0.0 ? publicDcfcTeslaCost
                                       : (publicDcfcCost > 0.0 ? publicDcfcCost : publicChargingCost);
            case "public":       return publicChargingCost; // legacy 3-way callers
            default:             return 0.0;
        }
    }

    /**
     * MD fork (2026-07): flat road-use excise [currency/kWh] for a charger type,
     * gated by scope. Applied additively and OUTSIDE the ToU multiplier by the
     * scorer. Scopes: "all" (home/work/public), "public" (L2/DCFC/DCFC_TESLA),
     * "dcfc" (DCFC/DCFC_TESLA only).
     */
    public double resolveExcise(String chargerType) {
        if (chargerType == null || roadExcisePerKWh <= 0.0) return 0.0;
        boolean isDcfc = "DCFC".equals(chargerType) || "DCFC_TESLA".equals(chargerType);
        boolean isPublic = isDcfc || "L2".equals(chargerType) || "L2F".equals(chargerType)
                || "public".equals(chargerType);
        switch (roadExciseScope) {
            case "dcfc":   return isDcfc ? roadExcisePerKWh : 0.0;
            case "public": return isPublic ? roadExcisePerKWh : 0.0;
            case "all":
            default:       return roadExcisePerKWh;   // home/work/public all charged
        }
    }

    public static final class Builder {
        private double marginalUtilityOfRangeAnxiety_soc;
        private double utilityOfEmptyBattery;
        private double marginalUtilityOfWalking_m;
        private double utilityOfHomeCharging;
        private double marginalUtilityOfSocDifference;
        private double defaultRangeAnxietyThreshold;
        private double betaMoney;
        private double alphaScaleCost;
        private double defaultHomeChargerPower;
        private double homeChargingCost;
        private double workChargingCost;
        private double publicChargingCost;
        private double publicL2Cost;
        private double publicDcfcCost;
        private double publicDcfcTeslaCost;
        private double roadExcisePerKWh;
        private String roadExciseScope;
        private double chargingTimeUtility_util_per_s;
        private double defaultPhevGasCostPerKwh;

        public Builder(final Scenario scenario) {
            this((UrbanEVConfigGroup) scenario.getConfig().getModules().get(UrbanEVConfigGroup.GROUP_NAME));
        }

        public Builder(final UrbanEVConfigGroup configGroup) {
            marginalUtilityOfRangeAnxiety_soc = configGroup.getRangeAnxietyUtility();
            utilityOfEmptyBattery = configGroup.getEmptyBatteryUtility();
            marginalUtilityOfWalking_m = configGroup.getWalkingUtility();
            utilityOfHomeCharging = configGroup.getHomeChargingUtility();
            marginalUtilityOfSocDifference = configGroup.getSocDifferenceUtility();
            defaultRangeAnxietyThreshold = configGroup.getDefaultRangeAnxietyThreshold();

            // Cost and ToU-related parameters: OmkarP.(2025)
            betaMoney = configGroup.getBetaMoney();
            alphaScaleCost = configGroup.getAlphaScaleCost();
            homeChargingCost = configGroup.getHomeChargingCost();
            workChargingCost = configGroup.getWorkChargingCost();
            publicChargingCost = configGroup.getPublicChargingCost();
            publicL2Cost = configGroup.getPublicL2Cost();
            publicDcfcCost = configGroup.getPublicDcfcCost();
            publicDcfcTeslaCost = configGroup.getPublicDcfcTeslaCost();
            roadExcisePerKWh = configGroup.getRoadExcisePerKWh();
            roadExciseScope = configGroup.getRoadExciseScope();
            if (!Double.isFinite(roadExcisePerKWh) || roadExcisePerKWh < 0.0) {
                roadExcisePerKWh = 0.0;
            }
            if (roadExciseScope == null) roadExciseScope = "all";
            defaultHomeChargerPower = configGroup.getDefaultHomeChargerPower();

            if (!Double.isFinite(alphaScaleCost) || alphaScaleCost < 0.0) {
                alphaScaleCost = 0.0;
            }
            if (!Double.isFinite(defaultRangeAnxietyThreshold) || defaultRangeAnxietyThreshold <= 0.0) {
                defaultRangeAnxietyThreshold = 0.2;
            }

            // MD fork (2026-07): PHEV gas fallback default rate
            defaultPhevGasCostPerKwh = configGroup.getPhevGasCostPerKwh();
            if (!Double.isFinite(defaultPhevGasCostPerKwh) || defaultPhevGasCostPerKwh <= 0.0) {
                defaultPhevGasCostPerKwh = 0.30;
            }

            // MD fork (2026): CHARGING_TIME utility (Anchor 1: opportunity cost of dwell)
            chargingTimeUtility_util_per_s = configGroup.getChargingTimeUtility();
            if (!Double.isFinite(chargingTimeUtility_util_per_s) || chargingTimeUtility_util_per_s > 0.0) {
                log.warn("ChargingBehaviourScoringParameters: chargingTimeUtility is positive or NaN ("
                        + chargingTimeUtility_util_per_s + "); defaulting to -6.0/3600 util/s.");
                chargingTimeUtility_util_per_s = -6.0 / 3600.0;
            }
        }

        public ChargingBehaviourScoringParameters build() {
            return new ChargingBehaviourScoringParameters(
                    marginalUtilityOfRangeAnxiety_soc,
                    utilityOfEmptyBattery,
                    marginalUtilityOfWalking_m,
                    utilityOfHomeCharging,
                    marginalUtilityOfSocDifference,
                    defaultRangeAnxietyThreshold,
                    betaMoney,
                    alphaScaleCost,
                    defaultHomeChargerPower,
                    homeChargingCost,
                    workChargingCost,
                    publicChargingCost,
                    publicL2Cost,
                    publicDcfcCost,
                    publicDcfcTeslaCost,
                    roadExcisePerKWh,
                    roadExciseScope,
                    chargingTimeUtility_util_per_s,
                    defaultPhevGasCostPerKwh
            );
        }
    }
}
