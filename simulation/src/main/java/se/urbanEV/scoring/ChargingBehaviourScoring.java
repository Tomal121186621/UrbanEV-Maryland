package se.urbanEV.scoring;

import com.google.inject.Inject;
import se.urbanEV.stats.ChargingBehaviorScoresCollector;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.scoring.SumScoringFunction;
import se.urbanEV.charging.ChargingCostUtils;

public class ChargingBehaviourScoring implements SumScoringFunction.ArbitraryEventScoring {

    public enum ScoreComponents {
        RANGE_ANXIETY,
        EMPTY_BATTERY,
        WALKING_DISTANCE,
        HOME_CHARGING,
        ENERGY_BALANCE,
        CHARGING_COST,  // OmkarP.(2025): cost term from charging prices
        CHARGING_TIME,  // MD fork (2026): opportunity-cost of dwell time (Anchor 1)
        GAS_FALLBACK    // MD fork (2026-07): PHEV charge-sustaining gasoline cost for unmet battery energy
    }

    private double score;
    private static final String CHARGING_IDENTIFIER = " charging";
    private static final String LAST_ACT_IDENTIFIER = " end";
    private static final double TOU_STEP_SEC = 15.0 * 60.0;
    private ChargingBehaviorScoresCollector chargingBehaviorScoresCollector = ChargingBehaviorScoresCollector.getInstance();

    final ChargingBehaviourScoringParameters params;
    Person person;
    private final double personBetaMoney;
    // MD fork (2026-07): PHEV gas fallback. PHEVs are not stranded at SOC 0 — they burn
    // gasoline in charge-sustaining mode. They therefore skip the BEV-style RANGE_ANXIETY /
    // EMPTY_BATTERY / ENERGY_BALANCE penalties and instead pay real fuel money for every
    // kWh of unmet battery energy (emitted as "gas_fallback" scoring events by
    // DriveDischargingHandler). phevGasCostPerKwh person attribute carries the per-model
    // rate = (gas $/gal / EPA charge-sustaining mpg) / (kWh/mi) — dollars per kWh-deficit.
    private final boolean isPhev;
    private final double phevGasCostPerKwh;
    static final String GAS_FALLBACK_ACT = "gas_fallback";

    @Inject
    public ChargingBehaviourScoring(final ChargingBehaviourScoringParameters params, Person person) {
        this.params = params;
        this.person = person;
        this.personBetaMoney = resolveBetaMoney(params, person);
        this.isPhev = "PHEV".equalsIgnoreCase(String.valueOf(person.getAttributes().getAttribute("evType")));
        this.phevGasCostPerKwh = resolvePhevGasCostPerKwh(params, person);
    }

    private static double resolvePhevGasCostPerKwh(ChargingBehaviourScoringParameters params, Person person) {
        Object attr = person.getAttributes().getAttribute("phevGasCostPerKwh");
        if (attr != null) {
            try {
                double v = Double.parseDouble(attr.toString());
                if (Double.isFinite(v) && v > 0.0) {
                    return v;
                }
            } catch (NumberFormatException ignored) { }
        }
        return params.defaultPhevGasCostPerKwh;
    }

    /**
     * MD fork (2026): per-agent betaMoney. Maryland plans carry an individualized
     * VOT-derived betaMoney person attribute (negative; observed range ~[-4.1, -0.79]).
     * Attribute wins; config-level params.betaMoney is the fallback (see
     * DISCOVERY_NOTES.md "betaMoney is already per-agent"). Non-negative, non-finite
     * or unparseable attribute values are rejected — cost must be a disutility.
     */
    private static double resolveBetaMoney(ChargingBehaviourScoringParameters params, Person person) {
        Object attr = person.getAttributes().getAttribute("betaMoney");
        if (attr != null) {
            try {
                double v = Double.parseDouble(attr.toString());
                if (Double.isFinite(v) && v < 0.0) {
                    return v;
                }
            } catch (NumberFormatException ignored) { }
        }
        return params.betaMoney;
    }

    @Override
    public void handleEvent(Event event) {
        if (event.getEventType().equals("scoring")) {
            ChargingBehaviourScoringEvent chargingBehaviourScoringEvent = (ChargingBehaviourScoringEvent) event;

            boolean costOnly = chargingBehaviourScoringEvent.isCostOnly();
            double soc = chargingBehaviourScoringEvent.getSoc();
            String activityType = chargingBehaviourScoringEvent.getActivityType();

            // MD fork (2026-07): PHEV gas fallback — unmet battery energy is driven in
            // charge-sustaining mode and costs real fuel money (per-agent betaMoney applied,
            // consistent with the CHARGING_COST term). BEV deficit events are telemetry only
            // (BEVs keep the EMPTY_BATTERY punishment below).
            if (GAS_FALLBACK_ACT.equals(activityType)) {
                Double deficitKWh = chargingBehaviourScoringEvent.getEnergyChargedKWh();
                if (isPhev && deficitKWh != null && deficitKWh > 0.0) {
                    double gasCost = deficitKWh * phevGasCostPerKwh;
                    double delta_score = personBetaMoney * params.alphaScaleCost * gasCost;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.GAS_FALLBACK, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.GAS_FALLBACK, person.getId());
                    score += delta_score;
                }
                return;
            }

            if (!costOnly) {

                // punish soc below threshold — BEV only: a PHEV with gas backup does not
                // experience range anxiety (fallback is priced via GAS_FALLBACK instead)
                Object thrObj = person.getAttributes().getAttribute("rangeAnxietyThreshold");
                double rangeAnxietyThreshold = (thrObj != null)
                        ? Double.parseDouble(thrObj.toString())
                        : params.defaultRangeAnxietyThreshold;

                if (!isPhev && soc > 0 && soc < rangeAnxietyThreshold) {
                    double delta_score = params.marginalUtilityOfRangeAnxiety_soc * (rangeAnxietyThreshold - soc) / rangeAnxietyThreshold;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.RANGE_ANXIETY, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.RANGE_ANXIETY, person.getId());
                    score += delta_score;
                }

                // severely punish empty battery — BEV only (a PHEV at SOC 0 drives on gas,
                // paying fuel cost via GAS_FALLBACK; it is not stranded)
                if (!isPhev && soc == 0) {
                    double delta_score = params.utilityOfEmptyBattery;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.EMPTY_BATTERY, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.EMPTY_BATTERY, person.getId());
                    score += delta_score;
                }

                // punish walking distance (only when charging)
                double walkingDistance = chargingBehaviourScoringEvent.getWalkingDistance();
                if (activityType.contains(CHARGING_IDENTIFIER)) {
                    // inverted utility based on Geurs, van Wee 2004 Equation (1)
                    double beta = 0.005;
                    double delta_score = params.marginalUtilityOfWalking_m * (1 - Math.exp(-beta * walkingDistance));
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.WALKING_DISTANCE, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.WALKING_DISTANCE, person.getId());
                    score += delta_score;
                }

                // reward charging at home
                // MD fix (2026-07-04): attribute presence is not ownership — the v2 plans
                // carry homeChargerPower=0.0 for agents without a charger; require > 0.
                boolean hasChargerAtHome = false;
                Object homePowerObj = person.getAttributes().getAttribute("homeChargerPower");
                if (homePowerObj != null) {
                    try {
                        hasChargerAtHome = Double.parseDouble(homePowerObj.toString()) > 0.0;
                    } catch (NumberFormatException ignored) { }
                }
                if (activityType.equals("home" + CHARGING_IDENTIFIER) && hasChargerAtHome) {
                    double delta_score = params.utilityOfHomeCharging;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.HOME_CHARGING, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.HOME_CHARGING, person.getId());
                    score += delta_score;
                }

                // punish difference between end soc and start soc to get realistic soc distribution
                // — BEV only: requiring battery-neutral days would force PHEVs to charge even
                // when the gas fallback is the cheaper (and chosen) option; their unmet energy
                // is already priced by GAS_FALLBACK.
                if (!isPhev && activityType.contains(LAST_ACT_IDENTIFIER)) {
                    if (activityType.contains(CHARGING_IDENTIFIER)) {
                        // Todo: Check whether this can be replaced by an estimation regarding how high the soc would have been if charging finished.
                        // This is a workaround
                        soc = 1;
                    }
                    // Calculate SOC difference
                    Double soc_diff =  soc - chargingBehaviourScoringEvent.getStartSoc();
                    if(soc_diff<=0){
                        // Only punish soc difference if SOC is smaller than at the beginning of the cycle.
                        double delta_score = params.marginalUtilityOfSocDifference * Math.abs(soc_diff);
                        chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.ENERGY_BALANCE, delta_score);
                        score += delta_score;
                    } else
                    {
                        chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.ENERGY_BALANCE, 0);
                    }
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.ENERGY_BALANCE, person.getId());
                }
            }


            // OmkarP.(2025): charging cost (price * ToU multiplier * betaMoney * etc.)
            Double energyChargedKWh = chargingBehaviourScoringEvent.getEnergyChargedKWh();
            String chargerType = chargingBehaviourScoringEvent.getChargerType();

            if (energyChargedKWh != null && energyChargedKWh > 0.0 && chargerType != null) {
                // MD 5-way fork: resolveUnitCost handles {home, work, L2, DCFC, DCFC_TESLA}
                // with fallback through legacy publicChargingCost. Legacy "public" tag also supported.
                double unitPricePerKWh = params.resolveUnitCost(chargerType);
                // MD fork (2026-07): flat road-use excise per kWh, applied OUTSIDE the
                // ToU multiplier (a state excise does not vary by time of day).
                double excisePerKWh = params.resolveExcise(chargerType);

                // MD fork (2026): per-agent betaMoney (attribute-first, config fallback)
                double effectiveBetaMoney = personBetaMoney * params.alphaScaleCost;
                if ((unitPricePerKWh > 0.0 || excisePerKWh > 0.0) && effectiveBetaMoney != 0.0) {
                    double touMultiplier = 1.0;
                    // TOU multiplier applies ONLY to home charging (residential utility tariff).
                    // Public L2 (ChargePoint/Blink/Volta/EVgo/Tesla Destination/etc.), workplace L2,
                    // DCFC, and Tesla SC all bill flat per MD operator pricing schedules (Phase 4).
                    // This matches Parishwad et al. upstream and MD market reality (most public L2
                    // is operator-priced flat, not utility-tariff pass-through).
                    boolean touApplies = "home".equalsIgnoreCase(chargerType);
                    if (touApplies) {
                        Double pricingTime = chargingBehaviourScoringEvent.getPricingTime();
                        double tForPricing = (pricingTime != null) ? pricingTime : event.getTime();

                        // Estimate charging duration from delivered energy and available power
                        double powerKW = params.defaultHomeChargerPower;
                        Object pHomeP = person.getAttributes().getAttribute("homeChargerPower");
                        if (pHomeP != null) {
                            try  {
                                powerKW = Double.parseDouble(pHomeP.toString());
                            } catch (Exception ignored) { }
                        }
                        if (powerKW > 0.0) {
                            double durationSec = (energyChargedKWh / powerKW) * 3600.0;
                            if (durationSec > 1.0) {
                                double tEnd = tForPricing + durationSec;
                                double wSum = 0.0;
                                double dtSum = 0.0;
                                for (double tt = tForPricing; tt < tEnd - 1e-6; tt += TOU_STEP_SEC) {
                                    double dt = Math.min(TOU_STEP_SEC, tEnd - tt);
                                    double m = ChargingCostUtils.getHourlyCostMultiplier(tt);
                                    wSum += m * dt;
                                    dtSum += dt;
                                }
                                touMultiplier = (dtSum > 0.0) ? (wSum / dtSum) : ChargingCostUtils.getHourlyCostMultiplier(tForPricing);
                            } else {
                                touMultiplier = ChargingCostUtils.getHourlyCostMultiplier(tForPricing);
                            }
                        } else {
                            touMultiplier = ChargingCostUtils.getHourlyCostMultiplier(tForPricing);
                        }
                    }

                    // tariff is ToU-scaled; excise is flat (added outside the multiplier)
                    double baseChargingCost = energyChargedKWh * (unitPricePerKWh * touMultiplier + excisePerKWh);
                    double delta_score = effectiveBetaMoney * baseChargingCost;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.CHARGING_COST, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.CHARGING_COST, person.getId());
                    // MD 5-way: record per-type session aggregates (sessions / kWh / cost)
                    chargingBehaviorScoresCollector.recordTypedSession(chargerType, energyChargedKWh, baseChargingCost);
                    score += delta_score;
                } else {
                    // Even with zero billable cost, count the session for per-type telemetry.
                    chargingBehaviorScoresCollector.recordTypedSession(chargerType, energyChargedKWh, 0.0);
                }

                // MD fork (2026): CHARGING_TIME — opportunity cost of dwell.
                // MD fork (2026-07): applies to DEDICATED-STOP charging only (DCFC /
                // DCFC_TESLA), where charging IS the activity and waiting is real.
                // Home, work, and public L2 are park-and-charge: the vehicle charges
                // DURING an activity the agent performs anyway (sleeping, working,
                // shopping), so plugging in has ~zero opportunity time cost.
                // History: costing dwell everywhere drove PHEV utility factors to ~0.2
                // (v1); costing it on all public types collapsed public L2 to 2% of
                // sessions (v2); observed US PHEV UF ~0.3-0.5 and ChargePoint L2
                // occupancy support the dedicated-stop-only rule.
                boolean dwellCosted = "DCFC".equalsIgnoreCase(chargerType)
                        || "DCFC_TESLA".equalsIgnoreCase(chargerType);
                Double effPowerKW = chargingBehaviourScoringEvent.getEffectiveChargingPowerKW();
                if (dwellCosted && effPowerKW != null && effPowerKW > 0.0) {
                    double durationSec = (energyChargedKWh / effPowerKW) * 3600.0;
                    double delta_score_time = params.chargingTimeUtility_util_per_s * durationSec;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.CHARGING_TIME, delta_score_time);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.CHARGING_TIME, person.getId());
                    score += delta_score_time;
                }
            }
        }
    }

    @Override public void finish() {}

    @Override
    public double getScore() {
        return score;
    }
}
