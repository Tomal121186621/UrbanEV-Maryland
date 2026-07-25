package se.urbanEV.config;

import org.matsim.core.config.ReflectiveConfigGroup;

import javax.validation.constraints.NotNull;
import javax.validation.constraints.Positive;
import javax.validation.constraints.PositiveOrZero;
import java.util.Map;
import org.apache.log4j.Logger;

public final class UrbanEVConfigGroup extends ReflectiveConfigGroup {
    private static final Logger log = Logger.getLogger(UrbanEVConfigGroup.class);

    public static final String GROUP_NAME = "urban_ev";

    private static final String RANGE_ANXIETY_UTILITY = "rangeAnxietyUtility";
    static final String RANGE_ANXIETY_UTILITY_EXP = "[utils/percent_points_of_soc_under_threshold] utility for going below battery threshold. negative";

    private static final String EMPTY_BATTERY_UTILITY = "emptyBatteryUtility";
    static final String EMPTY_BATTERY_UTILITY_EXP = "[utils] utility for empty battery. should not happen. very negative";

    private static final String WALKING_UTILITY = "walkingUtility";
    static final String WALKING_UTILITY_EXP = "[utils/m] utility for walking from charger to activity. negative";

    private static final String HOME_CHARGING_UTILITY = "homeChargingUtility";
    static final String HOME_CHARGING_UTILITY_EXP = "[utils] utility for using private home charger. positive";

    private static final String SOC_DIFFERENCE_UTILITY = "socDifferenceUtility";
    static final String SOC_DIFFERENCE_UTILITY_EXP = "[utils] utility for difference between start and end soc";

    public static final String VEHICLE_TYPES_FILE = "vehicleTypesFile";
    static final String VEHICLE_TYPES_FILE_EXP = "Location of the vehicle types file";

    public static final String DEFAULT_RANGE_ANXIETY_THRESHOLD = "defaultRangeAnxietyThreshold";
    static final String DEFAULT_RANGE_ANXIETY_THRESHOLD_EXP = "Default threshold for scoring. Set person attribute to overwrite. [% soc]";

    public static final String PARKING_SEARCH_RADIUS = "parkingSearchRadius";
    static final String PARKING_SEARCH_RADIUS_EXP = "Radius around activity location in which agents looks for available chargers [m]";

    public static final String MAXNUMBERSIMULTANEOUSPLANCHANGES = "maxNumberSimultaneousPlanChanges";
    static final String MAXNUMBERSIMULTANEOUSPLANCHANGES_EXP = "The maximum number of changes to a persons charging plan that are introduced in one replanning step.";

    public static final String TIMEADJUSTMENTPROBABILITY = "timeAdjustmentProbability";
    static final String TIMEADJUSTMENTPROBABILITY_EXP = "The probability with which a persons decides to adjust their activity end times in order to increase their chances for a free charging spot at their next activity.";

    public static final String MAXTIMEFLEXIBILITY = "maxTimeFlexibility";
    static final String MAXTIMEFLEXIBILITY_EXP = "The maximum time span a person is willing to adjust their activity end times in order to increase their chances for a free charging spot at their next activity [s].";

    public static final String GENERATE_HOME_CHARGERS_BY_PERCENTAGE = "generateHomeChargersByPercentage";
    static final String GENERATE_HOME_CHARGERS_BY_PERCENTAGE_EXP = "If set to true, home charger information from the population file will be ignored. Instead home chargers will be generated randomly given the homeChargerPercentage share. [true/false]";

    public static final String GENERATE_WORK_CHARGERS_BY_PERCENTAGE = "generateWorkChargersByPercentage";
    static final String GENERATE_WORK_CHARGERS_BY_PERCENTAGE_EXP = "If set to true, work charger information from the population file will be ignored. Instead work chargers will be generated randomly given the workChargerPercentage share. [true/false]";

    public static final String HOME_CHARGER_PERCENTAGE = "homeChargerPercentage";
    static final String HOME_CHARGER_PERCENTAGE_EXP = "Share of the population that will be equipped with a home charger if generateHomeChargersByPercentage is set to true. [%]";

    public static final String WORK_CHARGER_PERCENTAGE = "workChargerPercentage";
    static final String WORK_CHARGER_PERCENTAGE_EXP = "Share of the population that will be equipped with a work charger if generateWorkChargersByPercentage is set to true. [%]";

    public static final String DEFAULT_HOME_CHARGER_POWER = "defaultHomeChargerPower";
    static final String DEFAULT_HOME_CHARGER_POWER_EXP = "The power of home chargers if generateHomeChargersByPercentage is set to true [kW].";

    public static final String DEFAULT_WORK_CHARGER_POWER = "defaultWorkChargerPower";
    static final String DEFAULT_WORK_CHARGER_POWER_EXP = "The power of work chargers if generateWorkChargersByPercentage is set to true [kW].";



    // New parameters for charging costs and multipliers: OmkarP.(2025)
    private static final String HOME_CHARGING_COST = "homeChargingCost";
    static final String HOME_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at home chargers. 0.0 disables monetary charging at home.";

    private static final String WORK_CHARGING_COST = "workChargingCost";
    static final String WORK_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at work chargers. 0.0 disables monetary charging at work.";

    private static final String PUBLIC_CHARGING_COST = "publicChargingCost";
    static final String PUBLIC_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at public chargers. 0.0 disables monetary charging at public chargers. (Legacy 3-way lump; superseded by publicL2Cost/publicDcfcCost/publicDcfcTeslaCost.)";

    // Maryland 5-way per-type public charging costs (MD fork extension)
    private static final String PUBLIC_L2_COST = "publicL2Cost";
    static final String PUBLIC_L2_COST_EXP = "[currency/kWh] unit energy cost at public Level-2 chargers. If 0.0, falls back to publicChargingCost.";

    private static final String PUBLIC_DCFC_COST = "publicDcfcCost";
    static final String PUBLIC_DCFC_COST_EXP = "[currency/kWh] unit energy cost at public DCFC (non-Tesla) chargers. If 0.0, falls back to publicChargingCost.";

    private static final String PUBLIC_DCFC_TESLA_COST = "publicDcfcTeslaCost";
    static final String PUBLIC_DCFC_TESLA_COST_EXP = "[currency/kWh] unit energy cost at Tesla Supercharger (DCFC_TESLA) chargers. If 0.0, falls back to publicDcfcCost, then publicChargingCost.";

    private static final String ROAD_EXCISE_PER_KWH = "roadExcisePerKWh";
    static final String ROAD_EXCISE_PER_KWH_EXP = "[currency/kWh] flat EV road-use excise added to charging cost, OUTSIDE the ToU multiplier (does not vary by time of day). 0.0 = no policy.";
    private static final String ROAD_EXCISE_SCOPE = "roadExciseScope";
    static final String ROAD_EXCISE_SCOPE_EXP = "which charger types the road excise applies to: 'all' (home+work+public), 'public' (L2+DCFC+DCFC_TESLA), or 'dcfc' (DCFC+DCFC_TESLA only).";

    private static final String BETA_MONEY = "betaMoney";
    static final String BETA_MONEY_EXP = "[utils/currency] marginal utility of money for EV charging costs. Typically negative; 0.0 disables charging cost in scoring.";

    private static final String ALPHA_SCALE_COST = "alphaScaleCost";
    static final String ALPHA_SCALE_COST_EXP = "[dimensionless] technical scaling factor applied to betaMoney in EV scoring. 1.0 = no scaling; values << 1.0 dampen the money term.";

    private static final String ENABLE_SMART_CHARGING = "enableSmartCharging";
    private static final String ALPHA_SCALE_TEMPORAL = "alphaScaleTemporal";
    private static final String AWARENESS_FACTOR = "awarenessFactor";
    private static final String COINCIDENCE_FACTOR = "coincidenceFactor";

    // MD fork (2026): opportunity cost of charging dwell time.
    // Anchor 1: equal to negative `performing` utility of 6.0 util/hr -> -6.0/3600 util/s.
    private static final String CHARGING_TIME_UTILITY = "chargingTimeUtility";
    static final String CHARGING_TIME_UTILITY_EXP =
            "[utils/s] marginal utility of charging dwell time. Negative; default -0.001667 "
            + "(= -6.0 util/hr / 3600 s/hr; opportunity-cost anchor matching planCalcScore.performing).";

    // MD fork (2026-07): PHEV gas fallback — default $ per kWh of unmet battery energy
    // driven in charge-sustaining mode. Person attribute phevGasCostPerKwh overrides.
    private static final String PHEV_GAS_COST_PER_KWH = "phevGasCostPerKwh";
    static final String PHEV_GAS_COST_PER_KWH_EXP =
            "[currency/kWh] fallback gasoline cost per kWh of unmet battery energy for PHEVs "
            + "(= gas $/gal / charge-sustaining mpg / (kWh/mi)). Person attribute phevGasCostPerKwh overrides.";


    // Charger parameters
    private boolean generateHomeChargersByPercentage = false;

    private boolean generateWorkChargersByPercentage = false;

    @PositiveOrZero
    private double homeChargerPercentage = 0.0;

    @PositiveOrZero
    private double workChargerPercentage = 0.0;

    @PositiveOrZero
    private double defaultHomeChargerPower = 11.0;

    @PositiveOrZero
    private double defaultWorkChargerPower = 11.0;


    // Scoring parameters
    @NotNull
    private double rangeAnxietyUtility = -5;

    @NotNull
    private double emptyBatteryUtility = -10;

    @NotNull
    private double walkingUtility = -1;

    @NotNull
    private double homeChargingUtility = +1;

    @NotNull
    private double socDifferenceUtility = -10;

    @Positive
    private double defaultRangeAnxietyThreshold = 0.2;

    @NotNull
    private String vehicleTypesFile = null;

    // Charging parameters
    @Positive
    private int parkingSearchRadius = 500;

    // Replanning parameters

    @Positive
    private int maxNumberSimultaneousPlanChanges = 2;

    @PositiveOrZero
    private Double timeAdjustmentProbability = 0.1;

    @PositiveOrZero
    private int maxTimeFlexibility = 600;



    // Charging cost and ToU-related cost parameters: OmkarP.(2025)
    @NotNull
    private double betaMoney = 0.00;   // EV-specific marginal utility of money. Utils per currency unit

    @PositiveOrZero
    private double homeChargingCost = 0.0;

    @PositiveOrZero
    private double workChargingCost = 0.0;   // currency per kWh

    @PositiveOrZero
    private double publicChargingCost = 0.0; // currency per kWh (legacy 3-way lump)

    // Maryland 5-way per-type public charging costs (MD fork extension): OmkarP/MD.(2026)
    @PositiveOrZero
    private double publicL2Cost = 0.0;          // currency per kWh

    @PositiveOrZero
    private double publicDcfcCost = 0.0;        // currency per kWh

    @PositiveOrZero
    private double publicDcfcTeslaCost = 0.0;   // currency per kWh

    // MD fork (2026-07): road-use EXCISE per kWh — a flat per-kWh surcharge modeling
    // an EV road-funding fee. Applied ADDITIVELY and OUTSIDE the ToU multiplier (a
    // state excise does not vary by time of day), so smart-charging agents cannot
    // shift load to dodge it. Scope selects which charger types it applies to.
    @PositiveOrZero
    private double roadExcisePerKWh = 0.0;      // currency per kWh (0 = no policy)
    private String roadExciseScope = "all";     // all | public | dcfc

    @PositiveOrZero
    private double alphaScaleCost = 1.0;  // scaling factor for the costing

    @PositiveOrZero
    private double alphaScaleTemporal = 1.0;

    private boolean enableSmartCharging = false;
    private double awarenessFactor = 0.0;
    private double coincidenceFactor = 0.0;

    // [util/s] opportunity cost of charging dwell time (Anchor 1 = -6.0/3600).
    private double chargingTimeUtility_util_per_s = -6.0 / 3600.0;

    // [currency/kWh] PHEV charge-sustaining gasoline cost per kWh of battery deficit.
    // Fleet-weighted mean of research/phev_gas_fallback_costs.csv (AAA MD 2026-07-16 fuel
    // prices / EPA CS mpg); per-agent attribute phevGasCostPerKwh normally supplies the value.
    private double phevGasCostPerKwh = 0.364;




    public UrbanEVConfigGroup() {
        super(GROUP_NAME);
    }

    @Override
    public Map<String, String> getComments() {
        Map<String, String> map = super.getComments();
        map.put(RANGE_ANXIETY_UTILITY, RANGE_ANXIETY_UTILITY_EXP);
        map.put(EMPTY_BATTERY_UTILITY, EMPTY_BATTERY_UTILITY_EXP);
        map.put(WALKING_UTILITY, WALKING_UTILITY_EXP);
        map.put(HOME_CHARGING_UTILITY, HOME_CHARGING_UTILITY_EXP);
        map.put(SOC_DIFFERENCE_UTILITY, SOC_DIFFERENCE_UTILITY_EXP);
        map.put(VEHICLE_TYPES_FILE, VEHICLE_TYPES_FILE_EXP);
        map.put(PARKING_SEARCH_RADIUS, PARKING_SEARCH_RADIUS_EXP);
        map.put(DEFAULT_RANGE_ANXIETY_THRESHOLD, DEFAULT_RANGE_ANXIETY_THRESHOLD_EXP);
        map.put(MAXNUMBERSIMULTANEOUSPLANCHANGES, MAXNUMBERSIMULTANEOUSPLANCHANGES_EXP);
        map.put(TIMEADJUSTMENTPROBABILITY, TIMEADJUSTMENTPROBABILITY_EXP);
        map.put(MAXTIMEFLEXIBILITY, MAXTIMEFLEXIBILITY_EXP);
        map.put(GENERATE_HOME_CHARGERS_BY_PERCENTAGE, GENERATE_HOME_CHARGERS_BY_PERCENTAGE_EXP);
        map.put(GENERATE_WORK_CHARGERS_BY_PERCENTAGE, GENERATE_WORK_CHARGERS_BY_PERCENTAGE_EXP);
        map.put(HOME_CHARGER_PERCENTAGE, HOME_CHARGER_PERCENTAGE_EXP);
        map.put(WORK_CHARGER_PERCENTAGE, WORK_CHARGER_PERCENTAGE_EXP);
        map.put(DEFAULT_HOME_CHARGER_POWER, DEFAULT_HOME_CHARGER_POWER_EXP);
        map.put(DEFAULT_WORK_CHARGER_POWER, DEFAULT_WORK_CHARGER_POWER_EXP);

        // New charging cost parameters  (OmkarP. 2025)
        map.put(HOME_CHARGING_COST, HOME_CHARGING_COST_EXP);
        map.put(WORK_CHARGING_COST, WORK_CHARGING_COST_EXP);
        map.put(PUBLIC_CHARGING_COST, PUBLIC_CHARGING_COST_EXP);
        map.put(PUBLIC_L2_COST, PUBLIC_L2_COST_EXP);
        map.put(PUBLIC_DCFC_COST, PUBLIC_DCFC_COST_EXP);
        map.put(PUBLIC_DCFC_TESLA_COST, PUBLIC_DCFC_TESLA_COST_EXP);
        map.put(ROAD_EXCISE_PER_KWH, ROAD_EXCISE_PER_KWH_EXP);
        map.put(ROAD_EXCISE_SCOPE, ROAD_EXCISE_SCOPE_EXP);
        map.put(BETA_MONEY, BETA_MONEY_EXP);
        map.put(ALPHA_SCALE_COST, ALPHA_SCALE_COST_EXP);
        map.put(ENABLE_SMART_CHARGING, "Enable smart charging behavior: delayed start times, ToU awareness, and coincidence effect.");
        map.put(COINCIDENCE_FACTOR, "Probability that multiple rescheduled charging events start at the same time in the shifted low-ToU window.");
        map.put(AWARENESS_FACTOR, "Probability [0.0–1.0] of an agent being aware of ToU pricing and willing to shift charging start.");
        map.put(ALPHA_SCALE_TEMPORAL, "Temporal preference index in [0,2]. 0 biases shifted charging near start of low-ToU; " + "2 biases near end of low-ToU; 1 biases mid-window.");
        map.put(CHARGING_TIME_UTILITY, CHARGING_TIME_UTILITY_EXP);
        map.put(PHEV_GAS_COST_PER_KWH, PHEV_GAS_COST_PER_KWH_EXP);

        return map;
    }

    @StringGetter(MAXNUMBERSIMULTANEOUSPLANCHANGES)
    public int getMaxNumberSimultaneousPlanChanges() {
        return maxNumberSimultaneousPlanChanges;
    }

    @StringSetter(MAXNUMBERSIMULTANEOUSPLANCHANGES)
    public void setMaxNumberSimultaneousPlanChanges(int maxNumberSimultaneousPlanChanges) {
        this.maxNumberSimultaneousPlanChanges = maxNumberSimultaneousPlanChanges;
    }

    @StringGetter(TIMEADJUSTMENTPROBABILITY)
    public Double getTimeAdjustmentProbability() {
        return timeAdjustmentProbability;
    }

    @StringSetter(TIMEADJUSTMENTPROBABILITY)
    public void setTimeAdjustmentProbability(Double timeAdjustmentProbability) {
        this.timeAdjustmentProbability = timeAdjustmentProbability;
    }

    @StringGetter(MAXTIMEFLEXIBILITY)
    public int getMaxTimeFlexibility() {
        return maxTimeFlexibility;
    }

    @StringSetter(MAXTIMEFLEXIBILITY)
    public void setMaxTimeFlexibility(int maxTimeFlexibility) {
        this.maxTimeFlexibility = maxTimeFlexibility;
    }

    @StringGetter(RANGE_ANXIETY_UTILITY)
    public double getRangeAnxietyUtility() { return rangeAnxietyUtility; }

    @StringSetter(RANGE_ANXIETY_UTILITY)
    public void setRangeAnxietyUtility(double rangeAnxietyUtility) { this.rangeAnxietyUtility = rangeAnxietyUtility; }

    @StringGetter(EMPTY_BATTERY_UTILITY)
    public double getEmptyBatteryUtility() { return emptyBatteryUtility; }

    @StringSetter(EMPTY_BATTERY_UTILITY)
    public void setEmptyBatteryUtility(double emptyBatteryUtility) { this.emptyBatteryUtility = emptyBatteryUtility; }

    @StringGetter(WALKING_UTILITY)
    public double getWalkingUtility() { return walkingUtility; }

    @StringSetter(WALKING_UTILITY)
    public void setWalkingUtility(double walkingUtility) { this.walkingUtility = walkingUtility; }

    @StringGetter(HOME_CHARGING_UTILITY)
    public double getHomeChargingUtility() { return homeChargingUtility; }

    @StringSetter(HOME_CHARGING_UTILITY)
    public void setHomeChargingUtility(double homeChargingUtility) { this.homeChargingUtility = homeChargingUtility; }

    @StringGetter(SOC_DIFFERENCE_UTILITY)
    public double getSocDifferenceUtility() { return socDifferenceUtility; }

    @StringSetter(SOC_DIFFERENCE_UTILITY)
    public void setSocDifferenceUtility(double socDifferenceUtility) { this.socDifferenceUtility = socDifferenceUtility; }

    @StringGetter(DEFAULT_RANGE_ANXIETY_THRESHOLD)
    public double getDefaultRangeAnxietyThreshold() {
        return defaultRangeAnxietyThreshold;
    }

    @StringSetter(DEFAULT_RANGE_ANXIETY_THRESHOLD)
    public void setDefaultRangeAnxietyThreshold(double defaultRangeAnxietyThreshold) {
        this.defaultRangeAnxietyThreshold = defaultRangeAnxietyThreshold;
    }

    @StringGetter(VEHICLE_TYPES_FILE)
    public String getVehicleTypesFile() {
        return vehicleTypesFile;
    }

    @StringSetter(VEHICLE_TYPES_FILE)
    public void setVehicleTypesFile(String vehicleTypesFile) {
        this.vehicleTypesFile = vehicleTypesFile;
    }

    @StringGetter(PARKING_SEARCH_RADIUS)
    public int getParkingSearchRadius() {
        return parkingSearchRadius;
    }

    @StringSetter(PARKING_SEARCH_RADIUS)
    public void setParkingSearchRadius(int parkingSearchRadius) {
        this.parkingSearchRadius = parkingSearchRadius;
    }

    @StringGetter(GENERATE_HOME_CHARGERS_BY_PERCENTAGE)
    public boolean isGenerateHomeChargersByPercentage() {
        return generateHomeChargersByPercentage;
    }

    @StringSetter(GENERATE_HOME_CHARGERS_BY_PERCENTAGE)
    public void setGenerateHomeChargersByPercentage(boolean generateHomeChargersByPercentage) {
        this.generateHomeChargersByPercentage = generateHomeChargersByPercentage;
    }

    @StringGetter(GENERATE_WORK_CHARGERS_BY_PERCENTAGE)
    public boolean isGenerateWorkChargersByPercentage() {
        return generateWorkChargersByPercentage;
    }

    @StringSetter(GENERATE_WORK_CHARGERS_BY_PERCENTAGE)
    public void setGenerateWorkChargersByPercentage(boolean generateWorkChargersByPercentage) {
        this.generateWorkChargersByPercentage = generateWorkChargersByPercentage;
    }


    @StringGetter(HOME_CHARGER_PERCENTAGE)
    public double getHomeChargerPercentage() {
        return homeChargerPercentage;
    }

    @StringSetter(HOME_CHARGER_PERCENTAGE)
    public void setHomeChargerPercentage(double homeChargerPercentage) {
        this.homeChargerPercentage = homeChargerPercentage;
    }


    @StringGetter(WORK_CHARGER_PERCENTAGE)
    public double getWorkChargerPercentage() {
        return workChargerPercentage;
    }

    @StringSetter(WORK_CHARGER_PERCENTAGE)
    public void setWorkChargerPercentage(double workChargerPercentage) {
        this.workChargerPercentage = workChargerPercentage;
    }


    @StringGetter(DEFAULT_HOME_CHARGER_POWER)
    public double getDefaultHomeChargerPower() {
        return defaultHomeChargerPower;
    }

    @StringSetter(DEFAULT_HOME_CHARGER_POWER)
    public void setDefaultHomeChargerPower(double defaultHomeChargerPower) {
        this.defaultHomeChargerPower = defaultHomeChargerPower;
    }


    @StringGetter(DEFAULT_WORK_CHARGER_POWER)
    public double getDefaultWorkChargerPower() {
        return defaultWorkChargerPower;
    }

    @StringSetter(DEFAULT_WORK_CHARGER_POWER)
    public void setDefaultWorkChargerPower(double defaultWorkChargerPower) {
        this.defaultWorkChargerPower = defaultWorkChargerPower;
    }




    // Additional getters-setters for cost params: OmkarP.(2025)
    @StringGetter(HOME_CHARGING_COST)
    public double getHomeChargingCost() {
        return homeChargingCost;
    }

    @StringSetter(HOME_CHARGING_COST)
    public void setHomeChargingCost(double homeChargingCost) {
        this.homeChargingCost = homeChargingCost;
    }

    @StringGetter(WORK_CHARGING_COST)
    public double getWorkChargingCost() {
        return workChargingCost;
    }

    @StringSetter(WORK_CHARGING_COST)
    public void setWorkChargingCost(double workChargingCost) {
        this.workChargingCost = workChargingCost;
    }

    @StringGetter(PUBLIC_CHARGING_COST)
    public double getPublicChargingCost() {
        return publicChargingCost;
    }

    @StringSetter(PUBLIC_CHARGING_COST)
    public void setPublicChargingCost(double publicChargingCost) {
        this.publicChargingCost = publicChargingCost;
    }

    // Maryland 5-way per-type public costs
    @StringGetter(PUBLIC_L2_COST)
    public double getPublicL2Cost() {
        return publicL2Cost;
    }

    @StringSetter(PUBLIC_L2_COST)
    public void setPublicL2Cost(double publicL2Cost) {
        this.publicL2Cost = publicL2Cost;
    }

    @StringGetter(PUBLIC_DCFC_COST)
    public double getPublicDcfcCost() {
        return publicDcfcCost;
    }

    @StringSetter(PUBLIC_DCFC_COST)
    public void setPublicDcfcCost(double publicDcfcCost) {
        this.publicDcfcCost = publicDcfcCost;
    }

    @StringGetter(PUBLIC_DCFC_TESLA_COST)
    public double getPublicDcfcTeslaCost() {
        return publicDcfcTeslaCost;
    }

    @StringSetter(PUBLIC_DCFC_TESLA_COST)
    public void setPublicDcfcTeslaCost(double publicDcfcTeslaCost) {
        this.publicDcfcTeslaCost = publicDcfcTeslaCost;
    }

    // MD fork (2026-07): road-use excise
    @StringGetter(ROAD_EXCISE_PER_KWH)
    public double getRoadExcisePerKWh() {
        return roadExcisePerKWh;
    }

    @StringSetter(ROAD_EXCISE_PER_KWH)
    public void setRoadExcisePerKWh(double roadExcisePerKWh) {
        this.roadExcisePerKWh = roadExcisePerKWh;
    }

    @StringGetter(ROAD_EXCISE_SCOPE)
    public String getRoadExciseScope() {
        return roadExciseScope;
    }

    @StringSetter(ROAD_EXCISE_SCOPE)
    public void setRoadExciseScope(String roadExciseScope) {
        this.roadExciseScope = (roadExciseScope == null) ? "all"
                : roadExciseScope.trim().toLowerCase();
    }

    /**
     * Effective per-kWh cost resolver for a given charger type (Maryland 5-way).
     * Falls back through the layers: type-specific → public lump → 0.0.
     * Used by ChargingBehaviourScoring.
     */
    public double resolveUnitCost(String chargerType) {
        if (chargerType == null) return 0.0;
        switch (chargerType) {
            case "home":         return homeChargingCost;
            case "work":         return workChargingCost;
            case "L2":           return publicL2Cost > 0.0 ? publicL2Cost : publicChargingCost;
            case "DCFC":         return publicDcfcCost > 0.0 ? publicDcfcCost : publicChargingCost;
            case "DCFC_TESLA":   return publicDcfcTeslaCost > 0.0 ? publicDcfcTeslaCost
                                       : (publicDcfcCost > 0.0 ? publicDcfcCost : publicChargingCost);
            default:             return 0.0;
        }
    }

    @StringGetter(BETA_MONEY)
    public double getBetaMoney() {
        return betaMoney;
    }

    @StringSetter(BETA_MONEY)
    public void setBetaMoney(double betaMoney) {
        this.betaMoney = betaMoney;
    }

    @StringGetter(ALPHA_SCALE_COST)
    public double getAlphaScaleCost() {
        return alphaScaleCost;
    }

    @StringSetter(ALPHA_SCALE_COST)
    public void setAlphaScaleCost(double alphaScaleCost) {
        this.alphaScaleCost = alphaScaleCost;
    }

    @StringGetter(ENABLE_SMART_CHARGING)
    public boolean isEnableSmartCharging() {
        return enableSmartCharging;
    }

    @StringSetter(ENABLE_SMART_CHARGING)
    public void setEnableSmartCharging(boolean enableSmartCharging) {
        this.enableSmartCharging = enableSmartCharging;
    }

    @StringSetter(AWARENESS_FACTOR)
    public void setAwarenessFactor(double awarenessFactor) {
        if (awarenessFactor < 0.0 || awarenessFactor > 1.0) {
            log.warn("UrbanEVConfigGroup: awarenessFactor outside [0,1] (" + awarenessFactor + "), clamping.");
        }
        this.awarenessFactor = Math.max(0.0, Math.min(1.0, awarenessFactor));
    }

    @StringSetter(COINCIDENCE_FACTOR)
    public void setCoincidenceFactor(double coincidenceFactor) {
        if (coincidenceFactor < 0.0 || coincidenceFactor > 1.0) {
            log.warn("UrbanEVConfigGroup: coincidenceFactor outside [0,1] (" + coincidenceFactor + "), clamping.");
        }
        this.coincidenceFactor = Math.max(0.0, Math.min(1.0, coincidenceFactor));
    }

    @StringGetter(AWARENESS_FACTOR)
    public double getAwarenessFactor() {
        return awarenessFactor;
    }

    @StringGetter(COINCIDENCE_FACTOR)
    public double getCoincidenceFactor() {
        return coincidenceFactor;
    }

    @StringGetter(ALPHA_SCALE_TEMPORAL)
    public double getAlphaScaleTemporal() {
        return alphaScaleTemporal;
    }

    @StringSetter(ALPHA_SCALE_TEMPORAL)
    public void setAlphaScaleTemporal(double v) {
        if (!Double.isFinite(v)) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal is not finite (" + v + "), using 1.0.");
            this.alphaScaleTemporal = 1.0;
            return;
        }
        if (v < 0.0) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal < 0 (" + v + "), clamping to 0.0.");
            this.alphaScaleTemporal = 0.0;
        } else if (v > 2.0) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal > 2 (" + v + "), clamping to 2.0.");
            this.alphaScaleTemporal = 2.0;
        } else {
            this.alphaScaleTemporal = v;
        }
    }

    @StringGetter(CHARGING_TIME_UTILITY)
    public double getChargingTimeUtility() {
        return chargingTimeUtility_util_per_s;
    }

    @StringSetter(CHARGING_TIME_UTILITY)
    public void setChargingTimeUtility(double chargingTimeUtility) {
        this.chargingTimeUtility_util_per_s = chargingTimeUtility;
    }

    @StringGetter(PHEV_GAS_COST_PER_KWH)
    public double getPhevGasCostPerKwh() {
        return phevGasCostPerKwh;
    }

    @StringSetter(PHEV_GAS_COST_PER_KWH)
    public void setPhevGasCostPerKwh(double phevGasCostPerKwh) {
        this.phevGasCostPerKwh = phevGasCostPerKwh;
    }

    public void logIfSuspicious() {
        if (betaMoney > 0.0) {
            log.warn("UrbanEVConfigGroup: betaMoney > 0.0 detected (" + betaMoney + "). "
                    + "EV charging cost will increase utility; is that really intended?");
        }
        if (homeChargingCost < 0.0 || workChargingCost < 0.0 || publicChargingCost < 0.0
                || publicL2Cost < 0.0 || publicDcfcCost < 0.0 || publicDcfcTeslaCost < 0.0) {
            log.error("UrbanEVConfigGroup: negative charging cost detected. "
                    + "Please check home/work/public* charging costs in config.xml.");
        }
        if (publicL2Cost == 0.0 && publicDcfcCost == 0.0 && publicDcfcTeslaCost == 0.0 && publicChargingCost > 0.0) {
            log.info("UrbanEVConfigGroup: 5-way per-type public costs are unset; using legacy publicChargingCost lump for all public types.");
        }
    }
}
