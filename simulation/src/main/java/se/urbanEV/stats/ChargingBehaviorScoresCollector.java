package se.urbanEV.stats;

import se.urbanEV.scoring.ChargingBehaviourScoring;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;

/**
 * A class to collect all the data about the scoring of charging activities
 *
 * @author Lennart Adenaw on 09.09.2020
 */

public class ChargingBehaviorScoresCollector {

    private static final ChargingBehaviorScoresCollector OBJ = new ChargingBehaviorScoresCollector();
    private HashMap<ChargingBehaviourScoring.ScoreComponents, ArrayList<Double>> chargingBehaviorScoringComponents = new HashMap<>();
    private HashMap<ChargingBehaviourScoring.ScoreComponents, ArrayList<Id<Person>>> scoringPersons = new HashMap<>();

    // MD 5-way fork: per-charger-type session counters and cost totals (per iteration; reset on iteration end).
    // Keys: "home", "work", "L2", "DCFC", "DCFC_TESLA", "public" (legacy lump).
    private final HashMap<String, Long> sessionsByType = new HashMap<>();
    private final HashMap<String, Double> costByType = new HashMap<>();
    private final HashMap<String, Double> energyKwhByType = new HashMap<>();

    public static ChargingBehaviorScoresCollector getInstance(){
        return OBJ;
    }

    private ChargingBehaviorScoresCollector() {
        // Initialize charging component storage
        Arrays.stream(ChargingBehaviourScoring.ScoreComponents.values()).forEach(scoringComponent -> {
            // Initialize history containers
            chargingBehaviorScoringComponents.put(scoringComponent, new ArrayList<Double>());
            scoringPersons.put(scoringComponent, new ArrayList<Id<Person>>());
        });
    }

    public void addScoringComponentValue(ChargingBehaviourScoring.ScoreComponents component, double value)
    {
        chargingBehaviorScoringComponents.get(component).add(value);
    }

    public void addScoringPerson(ChargingBehaviourScoring.ScoreComponents component, Id<Person> personId){

        if(!scoringPersons.get(component).contains(personId))
        {
            scoringPersons.get(component).add(personId);
        }
    }

    public HashMap<ChargingBehaviourScoring.ScoreComponents, ArrayList<Double>> getChargingBehaviorScoringComponents()
    {
        return chargingBehaviorScoringComponents;
    }

    public HashMap<ChargingBehaviourScoring.ScoreComponents, ArrayList<Id<Person>>> getScoringPersons() {
        return scoringPersons;
    }

    public double getNumberOfScoringPersonsForComponent(ChargingBehaviourScoring.ScoreComponents scoreComponent){
        return scoringPersons.get(scoreComponent).size();
    }

    public double getComponentSum(ChargingBehaviourScoring.ScoreComponents scoreComponent){
        return chargingBehaviorScoringComponents.get(scoreComponent).stream().mapToDouble(a -> a).sum();
    }

    public double getComponentMean(ChargingBehaviourScoring.ScoreComponents scoreComponent){
        return chargingBehaviorScoringComponents.get(scoreComponent).stream().mapToDouble(a -> a).sum()/getNumberOfScoringPersonsForComponent(scoreComponent);
    }

    // ---- MD 5-way per-type session aggregation ----
    public synchronized void recordTypedSession(String chargerType, double energyKwh, double cost) {
        if (chargerType == null) chargerType = "unknown";
        sessionsByType.merge(chargerType, 1L, Long::sum);
        energyKwhByType.merge(chargerType, energyKwh, Double::sum);
        costByType.merge(chargerType, cost, Double::sum);
    }

    public HashMap<String, Long> getSessionsByType() { return sessionsByType; }
    public HashMap<String, Double> getCostByType() { return costByType; }
    public HashMap<String, Double> getEnergyKwhByType() { return energyKwhByType; }

    public void reset(){
        chargingBehaviorScoringComponents.keySet().forEach(scoringComponent -> {
            chargingBehaviorScoringComponents.get(scoringComponent).clear();
        });

        scoringPersons.keySet().forEach(scoringComponent -> {
            scoringPersons.get(scoringComponent).clear();
        });

        // MD 5-way per-type aggregates reset on iteration boundary
        sessionsByType.clear();
        costByType.clear();
        energyKwhByType.clear();
    }

}
