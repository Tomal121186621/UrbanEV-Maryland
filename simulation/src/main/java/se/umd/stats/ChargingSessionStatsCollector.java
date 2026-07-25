package se.umd.stats;

import com.google.inject.Inject;
import com.google.inject.Singleton;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.controler.IterationCounter;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.IterationStartsEvent;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.IterationStartsListener;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.events.handler.EventHandler;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import se.urbanEV.scoring.ChargingBehaviourScoringEventHandler;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Phase-3 MD addition: per-iter charging-session CSV writer.
 *
 * Listens to ChargingBehaviourScoringEvent (which carries chargerType for all
 * 5 types incl. home/work) and pairs stage-1 (session start, fired on
 * ActivityStartEvent) with stage-2 (session end, fired on ActivityEndEvent
 * with costOnly=true and the full cost+energy payload). Each completed pair
 * becomes one row joined with the agent's demographics (evMake/evModel/evType,
 * income, home coords, etc.) snapshotted at startup.
 *
 * Output: {iter}.charging_sessions.csv under ITERS/it.{N}/  - consumed by
 * analysis/iteration_plots.py post-smoke for figure sets {A 3-way occupancy,
 * B 5-way occupancy, C session distributions, D demographic stratifications}.
 *
 * Stage detection (from VehicleChargingHandler.java:326/388):
 *   - Stage-1 (start):  costOnly==false AND chargerType==null
 *   - Stage-2 (end):    costOnly==true  AND chargerType!=null
 */
@Singleton
public class ChargingSessionStatsCollector
        implements ChargingBehaviourScoringEventHandler,
                   StartupListener,
                   IterationStartsListener,
                   MobsimBeforeCleanupListener,
                   EventHandler {

    private static final Logger log = Logger.getLogger(ChargingSessionStatsCollector.class);

    @Inject
    private OutputDirectoryHierarchy controlerIO;
    @Inject
    private IterationCounter iterationCounter;
    @Inject
    private Scenario scenario;

    /** Per-person demographics snapshot, built once at startup. */
    private final Map<Id<Person>, Demographics> demographics = new HashMap<>();

    /** In-flight sessions: personId -> stage-1 record awaiting its stage-2 match. */
    private final Map<Id<Person>, OpenSession> inFlight = new HashMap<>();

    /** Completed sessions for the current iteration, flushed in notifyMobsimBeforeCleanup. */
    private final List<CompletedSession> completed = new ArrayList<>();

    private int sessionCounter = 0;

    // ------------------------------------------------------------------ startup

    @Override
    public void notifyStartup(StartupEvent event) {
        for (Person person : scenario.getPopulation().getPersons().values()) {
            demographics.put(person.getId(), Demographics.from(person));
        }
        log.info("ChargingSessionStatsCollector: snapshotted demographics for "
                + demographics.size() + " persons");
    }

    @Override
    public void notifyIterationStarts(IterationStartsEvent event) {
        inFlight.clear();
        completed.clear();
        sessionCounter = 0;
    }

    // ----------------------------------------------------------------- handler

    @Override
    public void handleEvent(ChargingBehaviourScoringEvent event) {
        Id<Person> personId = event.getPersonId();
        if (personId == null) return;

        if (!event.isCostOnly()) {
            // Stage-1: session start. Record context.
            OpenSession open = new OpenSession();
            open.timeStart = event.getTime();
            open.startSoc = event.getStartSoc();
            open.walkingDistance = event.getWalkingDistance();
            open.activityType = event.getActivityType();
            inFlight.put(personId, open);
        } else {
            // Stage-2: session end. Finalize.
            OpenSession open = inFlight.remove(personId);
            if (open == null) {
                // Stage-2 with no matching stage-1 — possible if iter reset mid-day.
                // Synthesize a one-event session so we don't lose the data point.
                open = new OpenSession();
                open.timeStart = event.getTime();
                open.startSoc = event.getStartSoc();
                open.walkingDistance = event.getWalkingDistance();
                open.activityType = event.getActivityType();
            }
            CompletedSession s = new CompletedSession();
            s.sessionId         = ++sessionCounter;
            s.personId          = personId;
            s.timeStart         = open.timeStart;
            s.timeEnd           = event.getTime();
            s.activityType      = event.getActivityType() != null
                                    ? event.getActivityType()
                                    : open.activityType;
            s.chargerType       = event.getChargerType();
            s.energyKwh         = event.getEnergyChargedKWh();
            s.socStart          = open.startSoc != null ? open.startSoc : event.getStartSoc();
            s.socEnd            = event.getSoc();
            s.walkingDistance   = open.walkingDistance != null
                                    ? open.walkingDistance
                                    : event.getWalkingDistance();
            s.pricingTime       = event.getPricingTime();
            completed.add(s);
        }
    }

    @Override
    public void reset(int iteration) {
        // Called by EventsManager at iteration start; keep state in sync.
        inFlight.clear();
    }

    // ----------------------------------------------------------------- flush

    @Override
    public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        int iter = iterationCounter.getIterationNumber();
        String path = controlerIO.getIterationFilename(iter, "charging_sessions.csv");
        try (CSVPrinter p = new CSVPrinter(
                Files.newBufferedWriter(Paths.get(path)),
                CSVFormat.DEFAULT.withDelimiter(';').withHeader(
                        "session_id", "person_id",
                        "time_start_s", "time_end_s", "duration_s",
                        "activity_type", "charger_type", "charger_type_3way",
                        "energy_kwh", "soc_start", "soc_end",
                        "walking_dist_m", "pricing_time_s",
                        "ev_make", "ev_model", "ev_type",
                        "income_usd", "hh_income_detailed", "income_bucket",
                        "home_x", "home_y",
                        "home_charger_power_kw", "work_charger_power_kw",
                        "smart_aware", "value_of_time", "beta_money"
                ))) {
            for (CompletedSession s : completed) {
                Demographics d = demographics.get(s.personId);
                if (d == null) d = Demographics.EMPTY;
                p.printRecord(
                        s.sessionId,
                        s.personId,
                        fmt(s.timeStart),
                        fmt(s.timeEnd),
                        fmt(s.timeEnd != null && s.timeStart != null
                                ? (s.timeEnd - s.timeStart) : null),
                        s.activityType,
                        s.chargerType,
                        threeWay(s.chargerType),
                        fmt(s.energyKwh),
                        fmt(s.socStart),
                        fmt(s.socEnd),
                        fmt(s.walkingDistance),
                        fmt(s.pricingTime),
                        d.evMake,
                        d.evModel,
                        d.evType,
                        fmt(d.income),
                        d.hhIncomeDetailed,
                        d.incomeBucket,
                        fmt(d.homeX),
                        fmt(d.homeY),
                        fmt(d.homeChargerPower),
                        fmt(d.workChargerPower),
                        d.smartAware,
                        fmt(d.valueOfTime),
                        fmt(d.betaMoney)
                );
            }
        } catch (IOException e) {
            log.error("Failed writing charging_sessions.csv for iter " + iter, e);
        }
        log.info("ChargingSessionStatsCollector iter " + iter + ": wrote "
                + completed.size() + " sessions to " + path);
    }

    // ------------------------------------------------------------- helpers

    private static String fmt(Double v) {
        return v == null ? "" : String.format("%.6f", v);
    }
    private static String fmt(Integer v) {
        return v == null ? "" : v.toString();
    }

    private static String threeWay(String chargerType) {
        if (chargerType == null) return "";
        switch (chargerType) {
            case "home": return "home";
            case "work": return "work";
            case "L2":
            case "DCFC":
            case "DCFC_TESLA":
            case "L1":
            default:     return "public";
        }
    }

    // ---------------------------------------------------------- inner types

    private static class OpenSession {
        Double timeStart;
        Double startSoc;
        Double walkingDistance;
        String activityType;
    }

    private static class CompletedSession {
        int sessionId;
        Id<Person> personId;
        Double timeStart, timeEnd;
        String activityType, chargerType;
        Double energyKwh, socStart, socEnd, walkingDistance, pricingTime;
    }

    /** Snapshot of agent-level attributes joined into each session row. */
    private static class Demographics {
        static final Demographics EMPTY = new Demographics();
        String evMake, evModel, evType;
        Double income;
        Integer hhIncomeDetailed;
        String incomeBucket;
        Double homeX, homeY;
        Double homeChargerPower, workChargerPower;
        String smartAware;
        Double valueOfTime, betaMoney;

        static Demographics from(Person person) {
            Demographics d = new Demographics();
            d.evMake            = strAttr(person, "evMake");
            d.evModel           = strAttr(person, "evModel");
            d.evType            = strAttr(person, "evType");
            d.income            = dblAttr(person, "income");
            d.hhIncomeDetailed  = intAttr(person, "hh_income_detailed");
            d.incomeBucket      = bucketIncome(d.hhIncomeDetailed);
            d.homeChargerPower  = dblAttr(person, "homeChargerPower");
            d.workChargerPower  = dblAttr(person, "workChargerPower");
            d.smartAware        = strAttr(person, "smartChargingAware");
            d.valueOfTime       = dblAttr(person, "valueOfTime");
            d.betaMoney         = dblAttr(person, "betaMoney");
            // Home coords: first activity of first plan that is type "home"
            if (person.getSelectedPlan() != null) {
                for (PlanElement pe : person.getSelectedPlan().getPlanElements()) {
                    if (pe instanceof Activity) {
                        Activity a = (Activity) pe;
                        if ("home".equals(a.getType()) && a.getCoord() != null) {
                            d.homeX = a.getCoord().getX();
                            d.homeY = a.getCoord().getY();
                            break;
                        }
                    }
                }
            }
            return d;
        }

        private static String strAttr(Person p, String key) {
            Object v = p.getAttributes().getAttribute(key);
            return v == null ? null : v.toString();
        }
        private static Double dblAttr(Person p, String key) {
            Object v = p.getAttributes().getAttribute(key);
            if (v == null) return null;
            if (v instanceof Number) return ((Number) v).doubleValue();
            try { return Double.parseDouble(v.toString()); } catch (NumberFormatException e) { return null; }
        }
        private static Integer intAttr(Person p, String key) {
            Object v = p.getAttributes().getAttribute(key);
            if (v == null) return null;
            if (v instanceof Number) return ((Number) v).intValue();
            try { return Integer.parseInt(v.toString()); } catch (NumberFormatException e) { return null; }
        }
        private static String bucketIncome(Integer hhDetailed) {
            if (hhDetailed == null) return "";
            // hh_income_detailed is a 1..8 bracket (MWCOG-derived).
            // L: 1-3 (<= ~$50k), M: 4-6 (~$50k-$150k), H: 7-8 (> ~$150k).
            if (hhDetailed <= 3) return "L";
            if (hhDetailed <= 6) return "M";
            return "H";
        }
    }
}
