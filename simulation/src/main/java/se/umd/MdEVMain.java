package se.umd;

import se.urbanEV.EvModule;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.planning.ChangeChargingBehaviour;
import se.urbanEV.scoring.ChargingBehaviourScoring;
import se.urbanEV.scoring.ChargingBehaviourScoringParameters;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Population;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.core.scoring.SumScoringFunction;
import java.io.IOException;

/**
 * Maryland UrbanEV main entry point.
 *
 * Forked from se.got.GotEVMain (Parishwad et al., TR-D 154 (2026) 105285).
 * The Java logic is currently identical to upstream — the Maryland-specific
 * customization (5-way charger-type coevolution, MD utility TOU, per-type
 * pricing) lives in:
 *   - scenarios/maryland/config_*.xml (this phase, Phase 2)
 *   - src/main/java/se/urbanEV/scoring/ChargingBehaviourScoring.java (Phase 3)
 *   - src/main/java/se/urbanEV/charging/VehicleChargingHandler.java (Phase 3)
 *   - src/main/java/se/urbanEV/planning/ChangeChargingBehaviourModule.java (Phase 3)
 *   - src/main/java/se/urbanEV/config/UrbanEVConfigGroup.java (Phase 3)
 *
 * Usage:
 *   java -Xmx24g -jar target/UrbanEV-Maryland-1.0-jar-with-dependencies.jar \
 *        scenarios/maryland/config_prod_100pct.xml [initIterations]
 */
public class MdEVMain {
    private static final Logger log = Logger.getLogger(se.umd.MdEVMain.class);
    private static final String SMART_CHARGING_COMPONENT = "SmartChargingEngine";

    public MdEVMain() {
    }

    public static void main(String[] args) throws IOException {

        String configPath = "";
        int initIterations = 20;
        if (args != null && args.length == 2) {
            configPath = args[0];
            initIterations = Integer.parseInt(args[1]);
        } else if (args != null && args.length == 1){
            configPath = args[0];
            initIterations = 0;
        }
        else{
            System.out.println("Config file missing. Please supply a config file path as a program argument.");
            throw new IOException("Could not start simulation. Config file missing.");
        }
        log.info("Config file path: " + configPath);
        log.info("Number of iterations to initialize SOC distribution: " + initIterations);

        ConfigGroup[] configGroups = new ConfigGroup[]{new EvConfigGroup(), new UrbanEVConfigGroup(),
                new org.matsim.contrib.roadpricing.RoadPricingConfigGroup()};
        Config config = ConfigUtils.loadConfig(configPath, configGroups);

        if (initIterations > 0) {
            Config initConfig = ConfigUtils.loadConfig(configPath, configGroups);
            initConfig.controler().setLastIteration(initIterations);
            initConfig.controler().setOutputDirectory(initConfig.controler().getOutputDirectory() + "/init");
            loadConfigAndRun(initConfig);

            EvConfigGroup evConfigGroup = (EvConfigGroup) config.getModules().get("ev");
            evConfigGroup.setVehiclesFile("output/init/output_evehicles.xml");
            config.controler().setOutputDirectory(config.controler().getOutputDirectory() + "/train");
        }
        loadConfigAndRun(config);
    }

    private static void loadConfigAndRun(Config config) {

        // MD perf: enable parallel event handling. Original upstream hardcoded =1 to
        // sidestep SmartChargingScheduler CME (memory: project_smartcharging_concurrency_fix.md);
        // that race is patched in this fork, so we can fan out to 6 threads on the
        // 8-core Ryzen 7 2700X. Watch for CME at iter 5-20; if it appears, revert to 1.
        config.parallelEventHandling().setNumberOfThreads(6);
        final Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);

        UrbanEVConfigGroup urbanEvCfg =
                (UrbanEVConfigGroup) controler.getConfig().getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        if (urbanEvCfg != null) {
            urbanEvCfg.logIfSuspicious();
        }

        controler.addOverridingModule(new EvModule());
        controler.configureQSimComponents(components -> {
            components.addNamedComponent(EvModule.EV_COMPONENT);

            if (urbanEvCfg != null && urbanEvCfg.isEnableSmartCharging()) {
                components.addNamedComponent(SMART_CHARGING_COMPONENT);
            }
        });

        controler.addOverridingQSimModule(new org.matsim.core.mobsim.qsim.AbstractQSimModule() {
            @Override
            protected void configureQSim() {
                bind(se.urbanEV.charging.VehicleChargingHandler.class).asEagerSingleton();
                bind(se.urbanEV.charging.SmartChargingEngine.class).asEagerSingleton();
                addQSimComponentBinding(SMART_CHARGING_COMPONENT)
                        .to(se.urbanEV.charging.SmartChargingEngine.class);
            }
        });

        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                addPlanStrategyBinding("ChangeChargingBehaviour").toProvider(ChangeChargingBehaviour.class);
            }
        });

        // MD-specific per-iter session stats CSV writer (feeds analysis/iteration_plots.py).
        controler.addOverridingModule(new MdStatsModule());

        // MD fork (2026-07): corridor / interstate VMT-toll scenarios (T5/T6).
        // Activates only when the config's roadpricing module names a toll file.
        org.matsim.contrib.roadpricing.RoadPricingConfigGroup rpCfg =
                org.matsim.core.config.ConfigUtils.addOrGetModule(config,
                        org.matsim.contrib.roadpricing.RoadPricingConfigGroup.class);
        if (rpCfg.getTollLinksFile() != null && !rpCfg.getTollLinksFile().isEmpty()) {
            log.info("RoadPricing enabled: " + rpCfg.getTollLinksFile());
            controler.addOverridingModule(new org.matsim.contrib.roadpricing.RoadPricingModule());
        }

        controler.setScoringFunctionFactory(new ScoringFunctionFactory() {
            @Override
            public ScoringFunction createNewScoringFunction(Person person) {
                ChargingBehaviourScoringParameters params =
                        new ChargingBehaviourScoringParameters.Builder(scenario).build();
                SumScoringFunction sum = new SumScoringFunction();
                sum.addScoringFunction(new ChargingBehaviourScoring(params, person));
                return sum;
            }
        });

        Population population = controler.getScenario().getPopulation();
        double awareness = (urbanEvCfg != null) ? urbanEvCfg.getAwarenessFactor() : 0.0;
        java.util.Random rng = new java.util.Random(controler.getConfig().global().getRandomSeed());

        int awareCount = 0;
        int total = 0;
        for (Person person : population.getPersons().values()) {
            person.getAttributes().putAttribute("subpopulation", "nonCriticalSOC");
            // Respect a per-person smartChargingAware attribute from the plans file
            // (income/age-based assignment); draw randomly only when absent.
            Object pre = person.getAttributes().getAttribute("smartChargingAware");
            boolean aware = (pre != null)
                    ? Boolean.parseBoolean(pre.toString())
                    : rng.nextDouble() <= awareness;
            person.getAttributes().putAttribute("smartChargingAware", aware);
            total++;
            if (aware) {
                awareCount++;
            }
        }

        log.info(String.format(
                "Smart charging awareness assignment: %.1f%% configured -> %d / %d persons marked smartChargingAware=true",
                awareness * 100.0, awareCount, total
        ));
        controler.run();
    }
}
