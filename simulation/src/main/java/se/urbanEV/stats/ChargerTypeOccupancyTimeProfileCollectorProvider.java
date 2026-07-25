package se.urbanEV.stats;

import com.google.inject.Inject;
import com.google.inject.Provider;
import se.urbanEV.charging.ChargingLogic;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import org.matsim.contrib.util.timeprofile.TimeProfileCharts;
import org.matsim.contrib.util.timeprofile.TimeProfileCharts.ChartType;
import org.matsim.contrib.util.timeprofile.TimeProfileCollector;
import org.matsim.contrib.util.timeprofile.TimeProfileCollector.ProfileCalculator;
import org.matsim.contrib.util.timeprofile.TimeProfiles;
import org.matsim.core.controler.MatsimServices;
import org.matsim.core.mobsim.framework.listeners.MobsimListener;

import java.awt.*;

/**
 * Phase-3 MD edit: bucket occupancy by the charger's typed attribute
 * (charger.getChargerType()), not by substring-matching the charger id.
 * Upstream's substring scheme dumped every MD charger into "public" because
 * MD ids are "l2_MD_xxx" / "dcfc_MD_xxx" / "dcfc_tesla_MD_xxx" and contain
 * neither "home" nor "work". The 5-way split below mirrors Phase-3 cost
 * resolution and matches the activity-suffix tag space used by
 * ChangeChargingBehaviourModule.
 */
public class ChargerTypeOccupancyTimeProfileCollectorProvider implements Provider<MobsimListener> {
	private final ChargingInfrastructure chargingInfrastructure;
	private final MatsimServices matsimServices;

	@Inject
	public ChargerTypeOccupancyTimeProfileCollectorProvider(ChargingInfrastructure chargingInfrastructure,
															MatsimServices matsimServices) {
		this.chargingInfrastructure = chargingInfrastructure;
		this.matsimServices = matsimServices;
	}

	@Override
	public MobsimListener get() {
		ProfileCalculator calc = createChargerOccupancyCalculator(chargingInfrastructure);
		TimeProfileCollector collector = new TimeProfileCollector(calc, 300, "charger_type_occupancy_time_profiles",
				matsimServices);
		collector.setChartTypes(ChartType.Line, ChartType.StackedArea);
		collector.setChartCustomizer((chart, chartType) -> {
			TimeProfileCharts.changeSeriesColors(chart,
					new Color(255,   0,   0),  // home
					new Color(  0,   0, 255),  // work
					new Color(  0, 200,   0),  // L2 (public; L1 folded in)
					new Color(255, 140,   0),  // DCFC
					new Color(200,   0, 200)   // DCFC_TESLA
			);
		});
		return collector;
	}

	public static ProfileCalculator createChargerOccupancyCalculator(
			final ChargingInfrastructure chargingInfrastructure) {
		// L1 (statewide n=2) and any null/unknown types are folded into L2 so the
		// occupancy total reconciles with chargingStats.csv without an OTHER column.
		String[] header = { "home", "work", "L2", "DCFC", "DCFC_TESLA" };
		return TimeProfiles.createProfileCalculator(header, () -> {
			int home = 0, work = 0, l2 = 0, dcfc = 0, dcfcTesla = 0;
			for (Charger c : chargingInfrastructure.getChargers().values()) {
				ChargingLogic logic = c.getLogic();
				int plugged = logic.getPluggedVehicles().size();
				if (plugged == 0) continue;
				String t = c.getChargerType();
				if (t == null) { l2 += plugged; continue; }
				switch (t) {
					case "home":       home      += plugged; break;
					case "work":       work      += plugged; break;
					case "DCFC":       dcfc      += plugged; break;
					case "DCFC_TESLA": dcfcTesla += plugged; break;
					case "L2":
					case "L1":
					default:           l2        += plugged; break;
				}
			}
			return new Integer[] { home, work, l2, dcfc, dcfcTesla };
		});
	}
}
