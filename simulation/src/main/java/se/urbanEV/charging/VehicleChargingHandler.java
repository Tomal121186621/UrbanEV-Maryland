/*
File originally created, published and licensed by contributors of the org.matsim.* project.
Please consider the original license notice below.
This is a modified version of the original source code!

Modified 2020 by Lennart Adenaw, Technical University Munich, Chair of Automotive Technology
email	:	lennart.adenaw@tum.de
*/

/* ORIGINAL LICENSE
 *  *********************************************************************** *
 * project: org.matsim.*
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 * copyright       : (C) 2016 by the members listed in the COPYING,        *
 *                   LICENSE and WARRANTY file.                            *
 * email           : info at matsim dot org                                *
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *   See also COPYING, LICENSE and WARRANTY file                           *
 *                                                                         *
 * *********************************************************************** */

package se.urbanEV.charging;
/*
 * created by jbischoff, 09.10.2018
 *  This is an events based approach to trigger vehicle charging. Vehicles will be charged as soon as a person begins a charging activity.
 */

import org.matsim.core.config.Config;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.ActivityEndEvent;
import org.matsim.api.core.v01.events.ActivityStartEvent;
import org.matsim.api.core.v01.events.PersonLeavesVehicleEvent;
import org.matsim.api.core.v01.events.handler.ActivityEndEventHandler;
import org.matsim.api.core.v01.events.handler.ActivityStartEventHandler;
import org.matsim.api.core.v01.events.handler.PersonLeavesVehicleEventHandler;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import org.matsim.contrib.util.PartialSort;
import org.matsim.contrib.util.distance.DistanceUtils;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.vehicles.Vehicle;

import javax.inject.Inject;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class VehicleChargingHandler
        implements ActivityStartEventHandler, ActivityEndEventHandler, PersonLeavesVehicleEventHandler,
        ChargingEndEventHandler, MobsimScopeEventHandler {

    private static final Logger log = Logger.getLogger(VehicleChargingHandler.class);

    public static final String CHARGING_IDENTIFIER = " charging";
    // MD 5-way fork: typed-suffix forms are "<X> charging-L2", "<X> charging-DCFC", "<X> charging-DCFC_TESLA".
    // Legacy untagged " charging" suffix is still recognized (home special-case + backward compat).
    public static final String CHARGING_TYPE_SEP = " charging-";

    /** Returns true if the activity type denotes any charging activity (typed or legacy untagged). */
    public static boolean isChargingActivity(String actType) {
        if (actType == null) return false;
        return actType.endsWith(CHARGING_IDENTIFIER) || actType.contains(CHARGING_TYPE_SEP);
    }

    /**
     * MD 5-way: parse the embedded charger-type suffix from an activity type.
     * Returns one of "home", "work", "L2", "DCFC", "DCFC_TESLA", or null when the
     * activity carries a legacy untagged " charging" suffix (treated as "any type allowed").
     */
    public static String parseChargerType(String actType) {
        if (actType == null) return null;
        int sep = actType.indexOf(CHARGING_TYPE_SEP);
        if (sep >= 0) {
            String suffix = actType.substring(sep + CHARGING_TYPE_SEP.length());
            // strip trailing " failed" if present
            int sp = suffix.indexOf(' ');
            if (sp > 0) suffix = suffix.substring(0, sp);
            // order matters: DCFC_TESLA before DCFC
            if (suffix.equals("L2") || suffix.equals("DCFC") || suffix.equals("DCFC_TESLA")) {
                return suffix;
            }
            return null;
        }
        if (actType.endsWith(CHARGING_IDENTIFIER)) {
            // legacy untagged: classify by activity-base prefix (home/work) for scoring
            if (actType.startsWith("home")) return "home";
            if (actType.startsWith("work")) return "work";
            return null; // public legacy — caller falls back to lump
        }
        return null;
    }
    private Map<Id<Person>, Id<Vehicle>> lastVehicleUsed = new HashMap<>();
    private Map<Id<ElectricVehicle>, Id<Charger>> vehiclesAtChargers = new HashMap<>();
    // Reverse map: EV -> driver. Needed by handleEvent(ChargingEndEvent) to
    // resolve the person + their current activity tag without scanning
    // lastVehicleUsed on every event. Populated alongside lastVehicleUsed.
    private final Map<Id<ElectricVehicle>, Id<Person>> vehicleToPerson = new HashMap<>();

    // track SOC and time at the start of each charging session- for smart rescheduling
    private final Map<Id<ElectricVehicle>, Double> chargeStartSoc = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Double> chargeStartTime = new HashMap<>();

    // SoC-driven unplug queue. ChargingEndEvent is dispatched by the parallel
    // event manager (SimStepParallelEventsManagerImpl); firing further events
    // from inside its handler races other worker threads and breaks the
    // chronological-ordering invariant. We instead capture the unplug intent
    // here and drain it from tick(now), which is invoked on the single-thread
    // mobsim main thread by SmartChargingEngine.doSimStep — a context where
    // firing UnpluggingEvent and ChargingBehaviourScoringEvent is safe.
    private final java.util.Deque<PendingSocUnplug> pendingSocCompletionUnplugs = new java.util.ArrayDeque<>();

    private static final class PendingSocUnplug {
        final Id<ElectricVehicle> evId;
        final Id<Charger> chargerId;
        final double endTime;
        final String actType;
        final Id<Person> personId;
        final String chargerType;
        PendingSocUnplug(Id<ElectricVehicle> evId, Id<Charger> chargerId, double endTime,
                         String actType, Id<Person> personId, String chargerType) {
            this.evId = evId; this.chargerId = chargerId; this.endTime = endTime;
            this.actType = actType; this.personId = personId; this.chargerType = chargerType;
        }
    }

    private final ChargingInfrastructure chargingInfrastructure;
    private final Network network;
    private final ElectricFleet electricFleet;
    private final Population population;
    private final int parkingSearchRadius;
    private final EventsManager eventsManager;
    private final double qsimEndTime;

    // scheduler for smart charging: OmkarP.(2025)
    private final UrbanEVConfigGroup urbanEvCfg;
    private final SmartChargingScheduler smartScheduler;

    @Inject
    public VehicleChargingHandler(ChargingInfrastructure chargingInfrastructure,
                                  Network network,
                                  ElectricFleet electricFleet,
                                  Population population,
                                  EventsManager eventsManager,
                                  MobsimScopeEventHandling events,
                                  UrbanEVConfigGroup urbanEVCfg,
                                  Config config) {
        this.chargingInfrastructure = chargingInfrastructure;
        this.network = network;
        this.electricFleet = electricFleet;
        this.population = population;
        this.eventsManager = eventsManager;
        this.parkingSearchRadius = urbanEVCfg.getParkingSearchRadius();
        this.urbanEvCfg = urbanEVCfg;

        this.qsimEndTime = config.qsim().getEndTime().seconds();
        this.smartScheduler = new SmartChargingScheduler(chargingInfrastructure, electricFleet, this);
        events.addMobsimScopeHandler(this);
    }

    /**
     * Implemented by omkarp, 10.01.2025
     * Called by SmartChargingScheduler when a deferred home-charging session actually plugs in.
     * Responsible for registering start SOC/time so that ActivityEndEvent can compute energyChargedKWh.
     */
    public void onSmartChargePlugged(Id<ElectricVehicle> evId, Id<Charger> chargerId, double time) {
        ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
        if (ev == null) {
            log.warn("onSmartChargePlugged: EV " + evId + " not found in fleet at t=" + time);
            return;
        }

        vehiclesAtChargers.put(evId, chargerId);

        double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
        chargeStartSoc.put(evId, socFraction);
        chargeStartTime.put(evId, time);

        if (log.isDebugEnabled()) {
            log.debug(String.format(
                    "onSmartChargePlugged: EV %s plugged at charger %s at t=%.0f, soc=%.3f",
                    evId, chargerId, time, socFraction
            ));
        }
    }

    @Override
	public void handleEvent(ActivityStartEvent event) {
		String actType = event.getActType();
		Id<Person> personId = event.getPersonId();
		Id<Vehicle> vehicleId = lastVehicleUsed.get(personId);
		if (vehicleId != null) {
			Id<ElectricVehicle> evId = Id.create(vehicleId, ElectricVehicle.class);
			if (electricFleet.getElectricVehicles().containsKey(evId)) {
				ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
				Person person = population.getPersons().get(personId);
				double walkingDistance = 0.0;

                if (isChargingActivity(event.getActType())) {
                    Activity activity = getActivity(person, event.getTime());
                    Coord activityCoord = activity != null
                            ? activity.getCoord()
                            : network.getLinks().get(event.getLinkId()).getCoord();
                    // MD 5-way: derive desired charger type from activity-tag suffix
                    String desiredType = parseChargerType(event.getActType());
                    // MD fix (2026-07-04): ALL parsed types are hard filters now, including
                    // "home"/"work". Bare home/work-charging acts can only bind to the agent's
                    // private charger (chargerType "home"/"work", allowlist-gated); agents
                    // without one get null -> "charging failed" -> replanned. Previously a
                    // bare "home charging" act could bind to any public charger within the
                    // search radius yet be labeled+billed "home".
                    String filterType = desiredType;
                    Charger selectedCharger = findBestCharger(activityCoord, ev, filterType);

                    if (selectedCharger != null) {
                        boolean isHomeChargingAct =
                                actType.startsWith("home") && actType.endsWith(CHARGING_IDENTIFIER);

                        // default: immediate charging (for non-home or smart disabled)
                        boolean smartEnabled = urbanEvCfg.isEnableSmartCharging() && isHomeChargingAct;

                        // Smart ToU aware rescheduling: OmkarP.(2025)
                        if (smartEnabled && activity != null) {
                            double arrivalTime = event.getTime();

                            double departureTime;
                            if (activity.getEndTime().isDefined()) {
                                departureTime = activity.getEndTime().seconds();
                            } else {
                                departureTime = qsimEndTime;
                            }

                            if (departureTime > arrivalTime) {
                                // energy missing (J - kWh)
                                double energyRequiredJ = ev.getBattery().getCapacity() - ev.getBattery().getSoc();
                                if (energyRequiredJ < 0.0) {
                                    energyRequiredJ = 0.0;
                                }
                                double energyRequiredKWh = energyRequiredJ / 3_600_000.0;

                                // approximate charging duration using person home charger power if present, else default (kW)
                                double powerKW = urbanEvCfg.getDefaultHomeChargerPower();
                                Object pHomeP = person.getAttributes().getAttribute("homeChargerPower");
                                if (pHomeP != null) {
                                    try { powerKW = Double.parseDouble(pHomeP.toString()); } catch (Exception ignored) { }
                                }

                                double effectiveKW = Math.max(0.1, 0.85 * powerKW);
                                double chargingDuration = (energyRequiredKWh / effectiveKW) * 3600.0;
                                double maxDur = Math.max(0.0, departureTime - arrivalTime);
                                chargingDuration = Math.min(chargingDuration, maxDur);

                                // Person-level awareness from attributes
                                Object awareAttr = person.getAttributes().getAttribute("smartChargingAware");
                                boolean isAware = false;
                                if (awareAttr instanceof Boolean) {
                                    isAware = (Boolean) awareAttr;
                                } else if (awareAttr instanceof String) {
                                    isAware = Boolean.parseBoolean((String) awareAttr);
                                }

                                double optimalStart = SmartChargingTouHelper.computeOptimalStartTime(
                                        arrivalTime,
                                        departureTime,
                                        chargingDuration,
                                        urbanEvCfg,
                                        selectedCharger,
                                        ev,
                                        isAware
                                );

                                if (log.isDebugEnabled()) {
                                    log.debug(String.format(
                                            "SmartCharging: person=%s aware=%s homeAct=true arr=%.0f dep=%.0f dur≈%.0fs - optimalStart=%.0f",
                                            personId, isAware, arrivalTime, departureTime, chargingDuration, optimalStart
                                    ));
                                }

                                if (optimalStart > arrivalTime + 1.0) {
                                    // schedule deferred plug-in
                                    smartScheduler.schedule(evId, selectedCharger.getId(), optimalStart);
                                    walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                                    log.info(String.format(
                                            "Smart home charging: EV %s defers from t=%.0f to t=%.0f (window %.0f–%.0f, dur≈%.0fs)",
                                            ev.getId(), arrivalTime, optimalStart, arrivalTime, departureTime, chargingDuration
                                    ));

                                } else {
                                    // optimum is effectively "now" (or agent not aware) fall back to immediate charging
                                    selectedCharger.getLogic().addVehicle(ev, arrivalTime);
                                    vehiclesAtChargers.put(evId, selectedCharger.getId());
                                    walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                                    double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
                                    chargeStartSoc.put(evId, socFraction);
                                    chargeStartTime.put(evId, arrivalTime);
                                }
                            } else {
                                // fallback immediate
                                double t = event.getTime();
                                selectedCharger.getLogic().addVehicle(ev, t);
                                vehiclesAtChargers.put(evId, selectedCharger.getId());
                                walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                                double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
                                chargeStartSoc.put(evId, socFraction);
                                chargeStartTime.put(evId, t);
                            }
                        } else {
                            // non-home charging or smart disabled: legacy behaviour
                            double t = event.getTime();
                            selectedCharger.getLogic().addVehicle(ev, t);
                            vehiclesAtChargers.put(evId, selectedCharger.getId());
                            walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                            double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
                            chargeStartSoc.put(evId, socFraction);
                            chargeStartTime.put(evId, t);
                        }

                    } else {
                        // if no charger was found, mark as failed attempt in plan
                        if (activity != null) {
                            actType = activity.getType() + " failed";
                            activity.setType(actType);
                        }
                    }
                }

                double time = event.getTime();
				double soc = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
				double startSoc = ev.getBattery().getStartSoc() / ev.getBattery().getCapacity();
				// if (soc <= 0) { log.error("EV " + ev.getId().toString() + " has empty battery."); }
				eventsManager.processEvent(new ChargingBehaviourScoringEvent(time, personId, soc,
						walkingDistance, actType, startSoc));
			}
		}
	}

    @Override
    public void handleEvent(ActivityEndEvent event) {
        if (isChargingActivity(event.getActType())) {
            Id<Vehicle> vehicleId = lastVehicleUsed.get(event.getPersonId());
            if (vehicleId != null) {
                Id<ElectricVehicle> evId = Id.create(vehicleId, ElectricVehicle.class);

                // cancel any deferred schedule if the charging act ends
                if (smartScheduler != null) {
                    smartScheduler.cancelIfScheduled(evId);
                }

                ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);

                // Emit cost-only scoring event for energy delivered during this
                // session. If the SoC-driven ChargingEndEvent path already
                // consumed startSoc/startTime, this is a no-op (the cost event
                // was already fired at natural completion).
                if (ev != null) {
                    Double startSocFrac = chargeStartSoc.remove(evId);
                    Double startTime    = chargeStartTime.remove(evId);
                    emitChargingCostEvent(ev, event.getPersonId(), event.getActType(),
                            event.getTime(), startSocFrac, startTime, null);
                }

                // Removal from charger logic. If the SoC-driven path already
                // unplugged us, vehiclesAtChargers no longer contains evId and
                // the block below is a no-op. Defensive plugged-check kept for
                // any out-of-band races (see project_charger_remove_race_fix).
                Id<Charger> chargerId = vehiclesAtChargers.remove(evId);
                if (chargerId != null) {
                    Charger charger = chargingInfrastructure.getChargers().get(chargerId);
                    ElectricVehicle plugCheckEv = electricFleet.getElectricVehicles().get(evId);
                    if (plugCheckEv != null && charger.getLogic().getPluggedVehicles().contains(plugCheckEv)) {
                        charger.getLogic().removeVehicle(plugCheckEv, event.getTime());
                    }
                }
            }
        }
    }

    /**
     * Build and fire the cost-only ChargingBehaviourScoringEvent for a completed
     * charging session. Shared by both termination paths:
     *   1. SoC-driven natural completion -> handleEvent(ChargingEndEvent)
     *   2. ActivityEnd while still charging -> handleEvent(ActivityEndEvent)
     *
     * Returns silently if no energy was delivered (startSocFrac null, or
     * deltaSoc <= 0). chargerTypeOverride lets the SoC-driven path pass the
     * charger's actual type instead of parsing it from the activity tag.
     */
    private void emitChargingCostEvent(ElectricVehicle ev, Id<Person> personId,
                                       String actType, double now,
                                       Double startSocFrac, Double startTime,
                                       String chargerTypeOverride) {
        if (startSocFrac == null) return;
        double currentSocFrac = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
        double deltaSocFrac   = currentSocFrac - startSocFrac;
        if (deltaSocFrac <= 0.0) return;

        double capacityKWh      = ev.getBattery().getCapacity() / 3_600_000.0;
        double energyChargedKWh = deltaSocFrac * capacityKWh;
        double pricingTime      = (startTime != null) ? startTime : now;

        // MD 5-way: classify charger type. If caller already knows the
        // actual charger (SoC-driven path), use it; else parse from activity tag.
        String chargerType = chargerTypeOverride;
        if (chargerType == null) {
            chargerType = parseChargerType(actType);
            if (chargerType == null) chargerType = "public";
        }

        // MD fork (2026): derive effective charging power in kW for the
        // dwell-time-cost scoring term. Try to resolve the charger the EV is
        // currently plugged at (vehiclesAtChargers map) and clamp by the
        // vehicle's max C-rate*capacity. If the charger ref is not in scope
        // here (rare race), fall back to null and let the scorer skip the term.
        Double effectiveChargingPowerKW = null;
        try {
            Id<Charger> chargerIdNow = vehiclesAtChargers.get(ev.getId());
            if (chargerIdNow != null) {
                Charger c = chargingInfrastructure.getChargers().get(chargerIdNow);
                if (c != null) {
                    double plugKW = c.getPlugPower() / 1000.0;  // W -> kW
                    double maxCrate = ev.getVehicleType().getMaxChargingRate();  // 1/h
                    double vehicleMaxKW = maxCrate * capacityKWh;
                    effectiveChargingPowerKW = Math.min(plugKW, vehicleMaxKW);
                }
            }
        } catch (Exception ignored) {
            // defensive: leave power null and skip the time term for this session
        }

        if (startTime != null && chargerType.equals("home")) {
            double durH  = Math.max(1e-6, (now - startTime) / 3600.0);
            double avgKW = energyChargedKWh / durH;
            log.info(String.format(
                    "HOME session: person=%s ev=%s start=%.0f end=%.0f kWh=%.2f avg_kW=%.2f",
                    personId, ev.getId(), startTime, now, energyChargedKWh, avgKW));
        }

        double socFrac          = currentSocFrac;
        double startSocForScore = ev.getBattery().getStartSoc() / ev.getBattery().getCapacity();
        eventsManager.processEvent(new ChargingBehaviourScoringEvent(
                now, personId, socFrac, 0.0, actType, startSocForScore,
                pricingTime, energyChargedKWh, chargerType, true,
                effectiveChargingPowerKW));
    }

    @Override
	public void handleEvent(PersonLeavesVehicleEvent event) {
		lastVehicleUsed.put(event.getPersonId(), event.getVehicleId());
		// Also maintain reverse map for ChargingEndEvent person-resolution.
		vehicleToPerson.put(Id.create(event.getVehicleId(), ElectricVehicle.class),
				event.getPersonId());
	}

	/**
	 * SoC-driven plug release: when ChargingLogicImpl signals natural completion
	 * (battery reached strategy's target SoC), free the plug immediately rather
	 * than holding it until the agent's parking activity ends. This eliminates
	 * the artifactual over-utilization where a completed DCFC session would
	 * occupy its port for the remaining 3-5 hours of a shopping/work activity.
	 *
	 * IMPORTANT: this handler runs on a parallel ProcessEventsRunnable thread.
	 * Firing events from here (e.g. via removeVehicle's UnpluggingEvent) races
	 * other worker threads and breaks SimStepParallelEventsManagerImpl's
	 * chronological-ordering invariant. We therefore only QUEUE the unplug
	 * here; the actual work is performed by drainPendingSocCompletionUnplugs()
	 * from tick(now), which is called on the single-thread mobsim main thread.
	 *
	 * The deferral cost is at most one chargeTimeStep (~15 s) — negligible vs
	 * the prior bug where plugs were held for hours after SoC fill.
	 */
	@Override
	public void handleEvent(ChargingEndEvent event) {
		Id<ElectricVehicle> evId = event.getVehicleId();
		Id<Charger> chargerId = vehiclesAtChargers.get(evId);
		if (chargerId == null) return;  // not tracked by us; ignore
		Charger charger = chargingInfrastructure.getChargers().get(chargerId);
		if (charger == null) return;
		ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
		if (ev == null) return;
		// MD patch scope: SoC-driven early unplug applies ONLY to public chargers
		// (L1/L2/DCFC/DCFC_TESLA) where multi-vehicle plug contention is the
		// observed bias vs ChargePoint. Per-person home/work synthetic chargers
		// (generated by UrbanEVConfigGroup.generate{Home,Work}ChargersByPercentage)
		// have their own ActivityEnd-driven unplug path with an existing race
		// fix (project_charger_remove_race_fix.md). Double-handling them caused
		// IllegalArgumentException("Vehicle X is not plugged at charger Y_work")
		// at iter 51 of C0 in the 2026-06-13 sensitivity sweep.
		String ct = charger.getChargerType();
		if ("home".equals(ct) || "work".equals(ct)) return;
		// Guard: if vehicle already gone from pluggedVehicles, our own deferred
		// removeVehicle ran (from a prior tick), or ActivityEnd removed it
		// already. Nothing to do.
		if (!charger.getLogic().getPluggedVehicles().contains(ev)) return;

		// Resolve driver + current activity tag for the scoring event payload.
		// These captures are SAFE to do on a worker thread: read-only lookups.
		Id<Person> personId = vehicleToPerson.get(evId);
		if (personId == null) return;
		Person person = population.getPersons().get(personId);
		String actType = "";
		if (person != null) {
			Activity currentAct = getActivity(person, event.getTime());
			if (currentAct != null) actType = currentAct.getType();
		}

		// Queue the unplug intent. Actual work happens in tick(now).
		synchronized (pendingSocCompletionUnplugs) {
			pendingSocCompletionUnplugs.add(new PendingSocUnplug(
					evId, chargerId, event.getTime(), actType, personId,
					charger.getChargerType()));
		}
	}

	/**
	 * Drains pendingSocCompletionUnplugs on the mobsim main thread (called from
	 * tick(now), itself called by SmartChargingEngine.doSimStep — a
	 * MobsimAfterSimStepListener). Emits cost-scoring event then unplugs.
	 *
	 * If the agent's ActivityEnd has already processed the unplug in the
	 * interval since SoC completion, the pluggedVehicles guard makes this a
	 * no-op for that entry.
	 *
	 * Uses `now` (current sim time) for the UnpluggingEvent timestamp to
	 * satisfy the parallel events manager's monotonicity check. The cost-event
	 * pricingTime still uses the original startTime, so TOU pricing is correct.
	 */
	private void drainPendingSocCompletionUnplugs(double now) {
		java.util.List<PendingSocUnplug> batch;
		synchronized (pendingSocCompletionUnplugs) {
			if (pendingSocCompletionUnplugs.isEmpty()) return;
			batch = new java.util.ArrayList<>(pendingSocCompletionUnplugs);
			pendingSocCompletionUnplugs.clear();
		}
		for (PendingSocUnplug p : batch) {
			ElectricVehicle ev = electricFleet.getElectricVehicles().get(p.evId);
			if (ev == null) continue;
			Charger charger = chargingInfrastructure.getChargers().get(p.chargerId);
			if (charger == null) continue;

			// May have been unplugged by ActivityEnd in the interval. Clean
			// bookkeeping but skip event firing.
			if (!charger.getLogic().getPluggedVehicles().contains(ev)) {
				vehiclesAtChargers.remove(p.evId);
				chargeStartSoc.remove(p.evId);
				chargeStartTime.remove(p.evId);
				continue;
			}

			Double startSocFrac = chargeStartSoc.remove(p.evId);
			Double startTime    = chargeStartTime.remove(p.evId);
			// Use charger's actual type (not parsed tag) so any tag/charger
			// mismatch is billed against the real rate.
			emitChargingCostEvent(ev, p.personId, p.actType, now,
					startSocFrac, startTime, p.chargerType);

			// removeVehicle fires UnpluggingEvent at `now`. Safe here because
			// we're on the mobsim main thread between sim steps. Defensive
			// try-catch: any residual race (e.g. multi-plug public charger with
			// concurrent ActivityEnd dispatch) throws IllegalArgumentException
			// from ChargingLogicImpl.removeVehicle if pluggedVehicles.remove
			// returns false. Swallow it — the EV is already unplugged, which is
			// the desired end-state. Keeps the sweep alive instead of crashing
			// at a late iteration after hours of compute.
			try {
				charger.getLogic().removeVehicle(ev, now);
			} catch (IllegalArgumentException ex) {
				// already unplugged by another path; ignore
			}
			vehiclesAtChargers.remove(p.evId);
		}
	}

	/**
	 * gets ativity from agent's plan by looking for current time
	 * @param person
	 * @param time
	 * @return
	 */
	private Activity getActivity(Person person, double time){
		Activity activity = null;
		List<PlanElement> planElements = person.getSelectedPlan().getPlanElements();
		for (int i = 0; i < planElements.size(); i++) {
			PlanElement planElement = planElements.get(i);
			if (planElement instanceof Activity) {
				if (((Activity) planElement).getEndTime().isDefined()) {
					double activityEndTime = ((Activity) planElement).getEndTime().seconds();
					if (activityEndTime > time || i == planElements.size() - 1) {
						activity = ((Activity) planElement);
						break;
					}
				}
				else if (i == planElements.size() - 1) {
					// Accept a missing end time for the last activity of a plan
					activity = ((Activity) planElement);
					break;
				}
				else{
					// There is a missing end time for an activity that is not the plan's last -> This should end in null being returned
					continue;
				}
			}
		}
		if (activity != null) {
			return activity;
		}
		else return null;
	}

	/**
	 * Tries to find closest free charger of fitting type in vicinity of activity location
	 * If a charger is private, only allowed vehicles can charge there
	 */

	private Charger findBestCharger(Coord stopCoord, ElectricVehicle electricVehicle) {
		return findBestCharger(stopCoord, electricVehicle, null);
	}

	/**
	 * MD 5-way overload: when {@code desiredType} is non-null, only chargers whose
	 * {@code getChargerType()} equals it are considered. Used to honor the
	 * activity-tag-embedded type preference (e.g. " charging-DCFC").
	 */
	private Charger findBestCharger(Coord stopCoord, ElectricVehicle electricVehicle, String desiredType) {

		List<Charger> filteredChargers = new ArrayList<>();
		chargingInfrastructure.getChargers().values().forEach(charger -> {
			// filter out private chargers unless vehicle is allowed
			boolean isPrivate = !charger.getAllowedVehicles().isEmpty();
			if (!isPrivate || charger.getAllowedVehicles().contains(electricVehicle.getId())) {
				// filter out chargers that are out of range
				if (DistanceUtils.calculateDistance(stopCoord, charger.getCoord()) < parkingSearchRadius) {
					// MD fix: private chargers (allowlist-gated, chargerType "home"/"work")
					// bypass the EV.charger_types membership check — ownership already
					// proves compatibility, and the EV side only declares public connector
					// standards (L1/L2/DCFC/DCFC_TESLA), never "home"/"work".
					// MD fork (2026-07): "L2F" (free public L2) uses the same connector as
					// "L2" — normalize for the EV-side capability check.
					String connType = "L2F".equals(charger.getChargerType()) ? "L2" : charger.getChargerType();
					if (isPrivate || electricVehicle.getChargerTypes().contains(connType)) {
						// MD 5-way: honor activity-tag-embedded type preference
						if (desiredType == null || desiredType.equals(charger.getChargerType())) {
							if ((charger.getLogic().getPluggedVehicles().size() < charger.getPlugCount())) {
								filteredChargers.add(charger);
							}
						}
					}
				}
			}
		});

		List<Charger> nearestChargers = PartialSort.kSmallestElements(1, filteredChargers.stream(),
				(charger) -> DistanceUtils.calculateSquaredDistance(stopCoord, charger.getCoord()));

		if (!nearestChargers.isEmpty()) {
			return nearestChargers.get(0);
		} else {
			 log.error("No charger found for EV " + electricVehicle.getId().toString() + " at location " + stopCoord.toString()
					 + (desiredType != null ? " (desiredType=" + desiredType + ")" : ""));
			return null;
		}
	}

    public void tick(double now) {
        if (smartScheduler != null) {
            smartScheduler.processDueTasks(now);
        }
        drainPendingSocCompletionUnplugs(now);
    }

    @Override
    public void reset(int iteration) {
        lastVehicleUsed.clear();
        vehicleToPerson.clear();
        vehiclesAtChargers.clear();
        chargeStartSoc.clear();
        chargeStartTime.clear();

        if (smartScheduler != null) {
            log.info(smartScheduler.consumeStatsLine(iteration));
            smartScheduler.reset();
        }
    }
}