package se.urbanEV.planning;

import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import se.urbanEV.scoring.ChargingBehaviourScoringEventHandler;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.*;
import org.matsim.api.core.v01.replanning.PlanStrategyModule;
import org.matsim.core.replanning.ReplanningContext;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;

public class ChangeChargingBehaviourModule implements PlanStrategyModule, ChargingBehaviourScoringEventHandler {

    private static final String CHARGING_IDENTIFIER = " charging";
    private static final String CHARGING_FAILED_IDENTIFIER = " charging failed";
    // MD 5-way fork: typed-suffix forms ("<X> charging-L2", "-DCFC", "-DCFC_TESLA").
    private static final String CHARGING_TYPE_SEP = " charging-";
    // MD fork (2026-07): "L2F" = free public L2 (AFDC pricing="Free" stations). Same
    // connector as L2 — any L2-capable vehicle may use it (see eligibleTypesFor and the
    // membership normalization in VehicleChargingHandler.findBestCharger).
    private static final String[] PUBLIC_TYPES = { "L2", "L2F", "DCFC", "DCFC_TESLA" };
    private static final String DEFAULT_PUBLIC_TYPE = "L2"; // cheapest, broadest availability

    /** True if the activity carries any charging suffix (typed or legacy untagged). */
    private static boolean hasChargingSuffix(String type) {
        return type != null && (type.endsWith(CHARGING_IDENTIFIER) || type.contains(CHARGING_TYPE_SEP));
    }

    /** True if the activity carries the failed suffix (handles both typed and legacy forms). */
    private static boolean hasFailedSuffix(String type) {
        return type != null && (type.endsWith(CHARGING_FAILED_IDENTIFIER) || type.endsWith(" failed"));
    }

    /** Strip any charging-related suffix (typed, legacy, or failed) from an activity type. */
    private static String stripChargingSuffix(String type) {
        if (type == null) return null;
        int sep = type.indexOf(CHARGING_TYPE_SEP);
        if (sep >= 0) return type.substring(0, sep);
        if (type.endsWith(CHARGING_FAILED_IDENTIFIER)) return type.substring(0, type.length() - CHARGING_FAILED_IDENTIFIER.length());
        if (type.endsWith(CHARGING_IDENTIFIER)) return type.substring(0, type.length() - CHARGING_IDENTIFIER.length());
        return type;
    }

    /** Returns the embedded type suffix ("L2"/"DCFC"/"DCFC_TESLA") if present, else null. */
    private static String getTypeSuffix(String type) {
        if (type == null) return null;
        int sep = type.indexOf(CHARGING_TYPE_SEP);
        if (sep < 0) return null;
        String suffix = type.substring(sep + CHARGING_TYPE_SEP.length());
        int sp = suffix.indexOf(' ');
        if (sp > 0) suffix = suffix.substring(0, sp);
        return suffix;
    }
    private final Random random = org.matsim.core.gbl.MatsimRandom.getLocalInstance();
    private Scenario scenario;
    private Network network;
    private Population population;
    private UrbanEVConfigGroup evCfg;
    private int maxNumberSimultaneousPlanChanges;
    private Double timeAdjustmentProbability;
    private int maxTimeFlexibility;

    ChangeChargingBehaviourModule(Scenario scenario) {
        this.scenario = scenario;
        this.network = this.scenario.getNetwork();
        this.population = this.scenario.getPopulation();
        this.evCfg = (UrbanEVConfigGroup) scenario.getConfig().getModules().get("urban_ev");
        this.maxNumberSimultaneousPlanChanges = evCfg.getMaxNumberSimultaneousPlanChanges();
        this.timeAdjustmentProbability = evCfg.getTimeAdjustmentProbability();
        this.maxTimeFlexibility = evCfg.getMaxTimeFlexibility();
    }

    @Override
    public void finishReplanning() {
    }

    @Override
    public void handlePlan(Plan plan) {
        int numberOfChanges = 1 + random.nextInt(maxNumberSimultaneousPlanChanges);

        for (int c = 0; c < numberOfChanges; c++ ) {
            List<PlanElement> planElements = plan.getPlanElements();
            int max = planElements.size();

            // get activity ids of activities with and without charging
            ArrayList<Integer> successfulChargingActIds = new ArrayList<>();
            ArrayList<Integer> failedChargingActIds = new ArrayList<>();
            ArrayList<Integer> noChargingActIds = new ArrayList<>();

            // loop starts at 2 because car should never be charging at start of simulation
            // MD 5-way: a "charging" activity may be either legacy untagged (" charging")
            // or typed (" charging-L2"/"-DCFC"/"-DCFC_TESLA"). Failed variants get stripped.
            for (int i = 2; i < max; i++) {
                PlanElement pe = planElements.get(i);
                if (pe instanceof Activity) {
                    Activity act = (Activity) pe;
                    String t = act.getType();
                    if (hasFailedSuffix(t)) {
                        // strip the " failed" marker; keep typed suffix if present (re-attempt with same type)
                        failedChargingActIds.add(i);
                        if (t.endsWith(CHARGING_FAILED_IDENTIFIER)) {
                            // legacy untagged failed: drop " failed" and keep " charging"
                            act.setType(t.substring(0, t.length() - " failed".length()));
                        } else if (t.endsWith(" failed")) {
                            // typed failed: e.g. "X charging-DCFC failed" → "X charging-DCFC"
                            act.setType(t.substring(0, t.length() - " failed".length()));
                        }
                    } else if (hasChargingSuffix(t)) {
                        successfulChargingActIds.add(i);
                    } else {
                        noChargingActIds.add(i);
                    }
                }
            }

            // with some probability try changing start time of failed charging activity (end time of previous activity)
            if (failedChargingActIds.size() > 0 && random.nextDouble() < timeAdjustmentProbability) {
                changeChargingActivityTime(planElements, failedChargingActIds);
            } else {
                // number of charging attempts that were successful
                int nSuccessfulCharging = successfulChargingActIds.size();
                // number of failed charging attempts
                int nFailedCharging = failedChargingActIds.size();
                // number of activities without charging attempt
                int nNoCharging = noChargingActIds.size();
                // sum of activities with successful attempts and activities without charging attempts
                int nTotal = nSuccessfulCharging + nNoCharging;

                // assign weights to different strategies based on successful and failed attempts
                double wChangeFailed = (nFailedCharging == 0 || nNoCharging == 0) ? 0 : 2;
                double wChangeSuccessful = (nSuccessfulCharging == 0 || nNoCharging == 0) ? 0 : 1;
                double wAdd = (double) nNoCharging / nTotal;
                double wRemove = (double) nSuccessfulCharging / nTotal;
                // MD 5-way: swap-type mutator weight scales with number of typed-public
                // successful activities. (Home charging activities are untagged and excluded.)
                int nTypedPublic = countTypedPublic(planElements, successfulChargingActIds);
                double wSwapType = (nTypedPublic == 0) ? 0 : ((double) nTypedPublic / nTotal);

                // decide which strategy to use: add/remove/change/swap-type
                double sumOfWeights = wAdd + wRemove + wChangeSuccessful + wChangeFailed + wSwapType;
                double w = sumOfWeights * random.nextDouble();
                w -= wChangeFailed;
                if (w <= 0) {
                    changeChargingActivity(planElements, failedChargingActIds, noChargingActIds, plan.getPerson());
                } else {
                    w -= wChangeSuccessful;
                    if (w <= 0) {
                        changeChargingActivity(planElements, successfulChargingActIds, noChargingActIds, plan.getPerson());
                    } else {
                        w -= wAdd;
                        if (w <= 0) {
                            addChargingActivity(planElements, noChargingActIds, plan.getPerson());
                        } else {
                            w -= wRemove;
                            if (w <= 0) {
                                removeChargingActivity(planElements, successfulChargingActIds);
                            } else {
                                swapChargerType(planElements, successfulChargingActIds, plan.getPerson());
                            }
                        }
                    }
                }
            }
        }
    }

    private void changeChargingActivityTime(List<PlanElement> planElements, ArrayList<Integer> failedChargingActIds) {
        // select random failed charging activity and try changing end time of previous activity
        int n = failedChargingActIds.size();
        if (n > 0) {
            int randInt = random.nextInt(n);
            int actId = failedChargingActIds.get(randInt);
            if (actId >= 2) {
                Activity selectedActivity = (Activity) planElements.get(actId);
                Leg previousLeg = (Leg) planElements.get(actId - 1);
                Activity previousActivity = (Activity) planElements.get(actId - 2);
                double timeDifference = random.nextDouble() * maxTimeFlexibility; // 0 to 10 minutes
                double earliestPossibleTime = 0;
                if (actId >= 4) {
                    earliestPossibleTime = ((Activity) planElements.get(actId - 4)).getEndTime().seconds();
                }
                if (previousActivity.getEndTime().seconds() - timeDifference > earliestPossibleTime) {
                    previousActivity.setEndTime(previousActivity.getEndTime().seconds() - timeDifference);
                    previousLeg.setDepartureTime(previousLeg.getDepartureTime().seconds() - timeDifference);
                    // Note: the failed-suffix strip earlier preserves the typed suffix on selectedActivity,
                    // so it already ends with " charging" or " charging-<TYPE>"; do not double-append.
                }
            }
        }
    }

    private void addChargingActivity(List<PlanElement> planElements, ArrayList<Integer> noChargingActIds) {
        addChargingActivity(planElements, noChargingActIds, null);
    }

    /**
     * MD 5-way overload: adds a charging suffix to a randomly-selected activity.
     * Home activities get the legacy " charging" suffix (home is a per-person special case).
     * Non-home activities get a typed suffix " charging-<TYPE>" sampled from the person's
     * eligible public types (defaults to L2 — cheapest, broadest availability).
     */
    private void addChargingActivity(List<PlanElement> planElements, ArrayList<Integer> noChargingActIds, Person person) {
        int n = noChargingActIds.size();
        if (n > 0) {
            int randInt = random.nextInt(n);
            int actId = noChargingActIds.get(randInt);
            Activity selectedActivity = (Activity) planElements.get(actId);
            String baseType = selectedActivity.getType();
            if (baseType != null && baseType.startsWith("home") && hasHomeCharger(person)) {
                // home + agent has a private home charger: legacy untagged suffix
                // (home special-case in VehicleChargingHandler). MD fix (2026-07-04):
                // agents WITHOUT a home charger fall through to the typed-public
                // branch so near-home charging is labeled AND billed as public —
                // previously they bound to public chargers but were billed "home".
                selectedActivity.setType(baseType + CHARGING_IDENTIFIER);
            } else if (baseType != null && baseType.startsWith("work") && hasWorkCharger(person)) {
                // work + agent has a private work charger: bare "work charging" tag so
                // VehicleChargingHandler.parseChargerType returns "work" and findBestCharger's
                // allowlist-bypass selects the agent's per-person private work charger.
                // Agents without workChargerPower fall through to the typed-public branch.
                selectedActivity.setType(baseType + CHARGING_IDENTIFIER);
            } else {
                // non-home/non-work-with-charger: typed suffix; uniformly random over eligible
                // public types so ExpBetaPlanSelector has all type-variants in the choice set.
                // Always-L2 seeding starved DCFC plans (<0.5% share at iter 10) regardless of
                // scoring gradient — the selector cannot pick plans that don't exist.
                Set<String> eligible = (person != null) ? eligibleTypesFor(person) : defaultEligibleTypes();
                List<String> elig = new ArrayList<>(eligible);
                String chosen = elig.isEmpty() ? DEFAULT_PUBLIC_TYPE : elig.get(random.nextInt(elig.size()));
                selectedActivity.setType(baseType + CHARGING_TYPE_SEP + chosen);
            }
        }
    }

    private void removeChargingActivity(List<PlanElement> planElements, ArrayList<Integer> successfulChargingActIds) {
        int n = successfulChargingActIds.size();
        if (n > 0) {
            int randInt = random.nextInt(n);
            int actId = successfulChargingActIds.get(randInt);
            Activity selectedActivity = (Activity) planElements.get(actId);
            selectedActivity.setType(stripChargingSuffix(selectedActivity.getType()));
        }
    }

    private void changeChargingActivity(List<PlanElement> planElements,
                                ArrayList<Integer> chargingActIds,
                                ArrayList<Integer> noChargingActIds,
                                Person person) {
        // remove charging tag from a random charging activity (typed or legacy)
        int chargingActId = chargingActIds.get(random.nextInt(chargingActIds.size()));
        Activity selectedActivity = (Activity) planElements.get(chargingActId);
        selectedActivity.setType(stripChargingSuffix(selectedActivity.getType()));

        // pick a nearby no-charging activity (gaussian) and tag it for charging
        double gaussId = 0.0;
        while (gaussId < 1 || gaussId > planElements.size()) {
            gaussId = 5 * random.nextGaussian() + chargingActId;
        }
        double dMin = planElements.size();
        int closestNoChargingActId = 0;
        for (int noChargingActId : noChargingActIds) {
            double d = Math.abs(gaussId - noChargingActId);
            if (d < dMin) {
                dMin = d;
                closestNoChargingActId = noChargingActId;
            }
        }
        Activity closestNoChargingActivity = (Activity) planElements.get(closestNoChargingActId);
        String baseType = closestNoChargingActivity.getType();
        if (baseType != null && baseType.startsWith("home") && hasHomeCharger(person)) {
            // mirror addChargingActivity: bare "home charging" only with a private home charger
            closestNoChargingActivity.setType(baseType + CHARGING_IDENTIFIER);
        } else if (baseType != null && baseType.startsWith("work") && hasWorkCharger(person)) {
            // mirror addChargingActivity: bare "work charging" when private work charger exists
            closestNoChargingActivity.setType(baseType + CHARGING_IDENTIFIER);
        } else {
            closestNoChargingActivity.setType(baseType + CHARGING_TYPE_SEP + DEFAULT_PUBLIC_TYPE);
        }
    }

    /**
     * MD 5-way mutator: swap the charger-type suffix of a randomly chosen typed-public
     * charging activity to a different eligible type for this vehicle.
     * Skips home/work-legacy activities (no typed suffix to swap).
     */
    private void swapChargerType(List<PlanElement> planElements,
                                 ArrayList<Integer> successfulChargingActIds,
                                 Person person) {
        // collect typed-public activities only
        ArrayList<Integer> typedIds = new ArrayList<>();
        for (Integer i : successfulChargingActIds) {
            Activity a = (Activity) planElements.get(i);
            if (getTypeSuffix(a.getType()) != null) typedIds.add(i);
        }
        if (typedIds.isEmpty()) return;
        Set<String> eligible = (person != null) ? eligibleTypesFor(person) : defaultEligibleTypes();
        if (eligible.size() < 2) return; // need at least 2 alternatives to swap

        int actId = typedIds.get(random.nextInt(typedIds.size()));
        Activity selectedActivity = (Activity) planElements.get(actId);
        String currentSuffix = getTypeSuffix(selectedActivity.getType());
        // candidates = eligible types minus the current one
        List<String> candidates = new ArrayList<>();
        for (String t : eligible) {
            if (!t.equals(currentSuffix)) candidates.add(t);
        }
        if (candidates.isEmpty()) return;
        String newSuffix = candidates.get(random.nextInt(candidates.size()));
        String baseType = stripChargingSuffix(selectedActivity.getType());
        selectedActivity.setType(baseType + CHARGING_TYPE_SEP + newSuffix);
    }

    /** Count successful charging activities that carry a typed suffix (used for swap weight). */
    private int countTypedPublic(List<PlanElement> planElements, ArrayList<Integer> successfulChargingActIds) {
        int n = 0;
        for (Integer i : successfulChargingActIds) {
            Activity a = (Activity) planElements.get(i);
            if (getTypeSuffix(a.getType()) != null) n++;
        }
        return n;
    }

    /**
     * MD 5-way: resolve the eligible public-charger types for a person's vehicle.
     * Reads from scenario.getVehicles() by person-id convention; falls back to person attribute
     * "charger_types" (comma-separated); finally defaults to all public types (optimistic —
     * findBestCharger will fail-and-mark for actually-incompatible swaps).
     */
    private Set<String> eligibleTypesFor(Person person) {
        Set<String> out = new HashSet<>();
        // Try scenario.getVehicles() via personId-as-vehicleId convention
        try {
            org.matsim.api.core.v01.Id<org.matsim.vehicles.Vehicle> vehId =
                    org.matsim.api.core.v01.Id.createVehicleId(person.getId().toString());
            org.matsim.vehicles.Vehicle veh = scenario.getVehicles().getVehicles().get(vehId);
            if (veh != null && veh.getType() != null) {
                Object ct = veh.getType().getEngineInformation().getAttributes().getAttribute("charger_types");
                if (ct != null) {
                    for (String t : ct.toString().split("[,;\\s]+")) {
                        if (t.isEmpty()) continue;
                        if (Arrays.asList(PUBLIC_TYPES).contains(t)) out.add(t);
                    }
                }
            }
        } catch (Exception ignored) { /* fall through */ }
        // Try person attribute fallback
        if (out.isEmpty()) {
            Object ct = person.getAttributes().getAttribute("charger_types");
            if (ct != null) {
                for (String t : ct.toString().split("[,;\\s]+")) {
                    if (t.isEmpty()) continue;
                    if (Arrays.asList(PUBLIC_TYPES).contains(t)) out.add(t);
                }
            }
        }
        if (out.isEmpty()) out = defaultEligibleTypes();
        // MD fork (2026-07): L2 capability implies L2F (same J1772 connector; fleet
        // files list connector standards, not price classes).
        if (out.contains("L2")) out.add("L2F");
        return out;
    }

    private static Set<String> defaultEligibleTypes() {
        return new HashSet<>(Arrays.asList(PUBLIC_TYPES));
    }

    /**
     * True iff the person has a private workplace charger (workChargerPower > 0).
     * Mirrors MobsimScopeEventHandling.addPrivateCharger's gate (line 165) so
     * "work charging" bare tags are only emitted for agents who actually own one.
     */
    private static boolean hasWorkCharger(Person person) {
        if (person == null) return false;
        Object v = person.getAttributes().getAttribute("workChargerPower");
        if (v == null) return false;
        try {
            return Double.parseDouble(v.toString()) > 0.0;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /**
     * MD fix (2026-07-04): mirror of {@link #hasWorkCharger}. Bare "home charging"
     * tags are only emitted for agents who actually own a home charger
     * (homeChargerPower &gt; 0); everyone else charges near home at PUBLIC
     * chargers via the typed-suffix branch and is billed public prices.
     */
    private static boolean hasHomeCharger(Person person) {
        if (person == null) return false;
        Object v = person.getAttributes().getAttribute("homeChargerPower");
        if (v == null) return false;
        try {
            return Double.parseDouble(v.toString()) > 0.0;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    @Override
    public void prepareReplanning(ReplanningContext replanningContext) {
    }

    @Override
    public void handleEvent(ChargingBehaviourScoringEvent event) {
        // 1) Ignore synthetic "cost-only" events from VehicleChargingHandler
        //    (these are only for monetary scoring and should not drive replanning).
        if (event.isCostOnly()) {
            return;
        }

        // 2) Null guards: if SOC or startSOC is missing, do not touch subpopulation.
        Double socObj = event.getSoc();
        Double startSocObj = event.getStartSoc();
        String actType = event.getActivityType();

        if (socObj == null || startSocObj == null || actType == null) {
            return;
        }

        double soc = socObj;
        double startSoc = startSocObj;
        boolean isLastAct = actType.contains("end");

        // 3) Critical if:
        //    - battery is empty at any scoring event, OR
        //    - at the last activity, SOC dropped far from start SOC in a "bad" way.
        boolean isCritical;

        if (soc <= 0.0) {
            // Empty battery → always critical.
            isCritical = true;
        } else if (isLastAct) {
            double deltaSoc = Math.abs(soc - startSoc);
            // Use a probabilistic threshold as before, but keep it bounded and explicit.
            double threshold = random.nextDouble();
            isCritical = deltaSoc > threshold;
        } else {
            // Intermediate activities are not decisive for (non-)critical classification.
            isCritical = false;
        }

        Person person = population.getPersons().get(event.getPersonId());
        if (person == null) {
            return;
        }

        if (isCritical) {
            // Mark agent as "criticalSOC" → always replanned via strategy settings.
            person.getAttributes().putAttribute("subpopulation", "criticalSOC");
        } else {
            // Reset to default "nonCriticalSOC" for standard replanning probability.
            person.getAttributes().putAttribute("subpopulation", "nonCriticalSOC");
        }
    }

    @Override
    public void reset(int iteration) {
    }
}
