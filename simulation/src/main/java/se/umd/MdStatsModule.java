package se.umd;

import org.matsim.core.controler.AbstractModule;
import se.umd.stats.ChargingSessionStatsCollector;
import se.urbanEV.stats.ChargingTimeSavedAnalyzer;

/**
 * Maryland-specific stats wiring. Registers the per-iter charging-session
 * CSV writer (which underpins analysis/iteration_plots.py post-smoke).
 *
 * Kept separate from upstream se.urbanEV.stats.EvStatsModule so the upstream
 * Parishwad code stays read-only per the project's fork policy.
 */
public class MdStatsModule extends AbstractModule {
    @Override
    public void install() {
        bind(ChargingSessionStatsCollector.class).asEagerSingleton();
        addEventHandlerBinding().to(ChargingSessionStatsCollector.class);
        addControlerListenerBinding().to(ChargingSessionStatsCollector.class);
        addMobsimListenerBinding().to(ChargingSessionStatsCollector.class);

        // MD fork (2026): per-iter time-saved analyzer + JFreeChart plots.
        bind(ChargingTimeSavedAnalyzer.class).asEagerSingleton();
        addControlerListenerBinding().to(ChargingTimeSavedAnalyzer.class);
    }
}
