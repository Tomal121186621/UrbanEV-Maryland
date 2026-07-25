package se.urbanEV.stats;

import com.google.inject.Inject;
import com.google.inject.Singleton;
import org.apache.log4j.Logger;
import org.jfree.chart.ChartFactory;
import org.jfree.chart.JFreeChart;
import org.jfree.chart.plot.PlotOrientation;
import org.jfree.chart.plot.XYPlot;
import org.jfree.chart.renderer.xy.XYLineAndShapeRenderer;
import org.jfree.data.category.DefaultCategoryDataset;
import org.jfree.data.statistics.HistogramDataset;
import org.jfree.data.statistics.HistogramType;
import org.jfree.data.xy.XYSeries;
import org.jfree.data.xy.XYSeriesCollection;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.events.ShutdownEvent;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import org.matsim.core.controler.listener.ShutdownListener;
import org.matsim.core.controler.listener.StartupListener;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * MD fork (2026): per-iteration analyzer that reads
 * {iter}.charging_sessions.csv (written by ChargingSessionStatsCollector),
 * computes time saved per session vs an L2 (11 kW) baseline, aggregates by
 * agent and charger type, writes two CSVs and two PNGs per iter, and a master
 * trajectory CSV + PNG across iterations.
 *
 * time_saved_h = (energy_kwh / 11 kW) - (energy_kwh / effectivePower_kW)
 *   positive  -> session was faster than L2 (DCFC, DCFC_TESLA)
 *   ~0        -> L2 session
 *   negative  -> slower than L2 (should not occur in MD config)
 */
@Singleton
public class ChargingTimeSavedAnalyzer
        implements StartupListener, IterationEndsListener, ShutdownListener {

    private static final Logger log = Logger.getLogger(ChargingTimeSavedAnalyzer.class);

    private static final double L2_BASELINE_KW = 11.0;

    /** Default effective kW by charger_type (used when CSV lacks the optional column). */
    private static final Map<String, Double> DEFAULT_POWER_KW;
    static {
        Map<String, Double> m = new HashMap<>();
        m.put("home", 11.0);
        m.put("work", 11.0);
        m.put("L2", 11.0);
        m.put("DCFC", 150.0);
        m.put("DCFC_TESLA", 250.0);
        DEFAULT_POWER_KW = Collections.unmodifiableMap(m);
    }

    @Inject
    private OutputDirectoryHierarchy controlerIO;

    /** Path of the master CSV (one row per iteration). Lazily resolved on first iter. */
    private Path masterCsv;

    public ChargingTimeSavedAnalyzer() { }

    // -------------------------------------------------- StartupListener

    @Override
    public void notifyStartup(StartupEvent event) {
        // controlerIO is injected by Guice. Defer master-CSV path resolution
        // until we have an iteration filename to anchor "output dir" against.
        log.info("ChargingTimeSavedAnalyzer: ready (L2 baseline = " + L2_BASELINE_KW + " kW).");
    }

    // -------------------------------------------------- IterationEndsListener

    @Override
    public void notifyIterationEnds(IterationEndsEvent event) {
        int iter = event.getIteration();
        String sessionsPath = controlerIO.getIterationFilename(iter, "charging_sessions.csv");
        Path csv = Paths.get(sessionsPath);
        if (!Files.exists(csv)) {
            log.warn("ChargingTimeSavedAnalyzer iter " + iter + ": missing " + sessionsPath);
            return;
        }

        List<SessionRow> sessions;
        try {
            sessions = readSessions(csv);
        } catch (IOException e) {
            log.error("ChargingTimeSavedAnalyzer iter " + iter + ": failed reading CSV", e);
            return;
        }

        if (sessions.isEmpty()) {
            log.info("ChargingTimeSavedAnalyzer iter " + iter + ": no sessions, skipping plots.");
            return;
        }

        // Aggregations
        Map<String, double[]> byAgent = new LinkedHashMap<>();   // personId -> [totalSavedH, nSessions]
        Map<String, double[]> byType  = new LinkedHashMap<>();   // chargerType -> [totalSavedH, nSessions]
        double totalSavedH = 0.0;
        int nSessions = 0;

        for (SessionRow s : sessions) {
            if (s.energyKwh <= 0.0 || Double.isNaN(s.energyKwh)) continue;
            double powerKW = s.effectivePowerKW;
            if (powerKW <= 0.0 || Double.isNaN(powerKW)) {
                Double def = DEFAULT_POWER_KW.get(s.chargerType);
                powerKW = (def != null) ? def : L2_BASELINE_KW;
            }
            double actualH   = s.energyKwh / powerKW;
            double baselineH = s.energyKwh / L2_BASELINE_KW;
            double savedH    = baselineH - actualH;

            byAgent.computeIfAbsent(s.personId, k -> new double[]{0.0, 0.0});
            double[] a = byAgent.get(s.personId);
            a[0] += savedH; a[1] += 1.0;

            String t = (s.chargerType == null || s.chargerType.isEmpty()) ? "unknown" : s.chargerType;
            byType.computeIfAbsent(t, k -> new double[]{0.0, 0.0});
            double[] bt = byType.get(t);
            bt[0] += savedH; bt[1] += 1.0;

            totalSavedH += savedH;
            nSessions++;
        }

        // Write per-agent CSV
        String perAgentPath = controlerIO.getIterationFilename(iter, "charging_time_saved_per_agent.csv");
        try (BufferedWriter w = Files.newBufferedWriter(Paths.get(perAgentPath))) {
            w.write("person_id,n_sessions,total_time_saved_h\n");
            for (Map.Entry<String, double[]> e : byAgent.entrySet()) {
                w.write(String.format("%s,%d,%.6f%n",
                        e.getKey(), (int) e.getValue()[1], e.getValue()[0]));
            }
        } catch (IOException e) {
            log.error("ChargingTimeSavedAnalyzer iter " + iter + ": per-agent CSV write failed", e);
        }

        // Write by-type CSV
        String byTypePath = controlerIO.getIterationFilename(iter, "charging_time_saved_by_type.csv");
        try (BufferedWriter w = Files.newBufferedWriter(Paths.get(byTypePath))) {
            w.write("charger_type,n_sessions,total_time_saved_h,mean_time_saved_h_per_session\n");
            for (Map.Entry<String, double[]> e : byType.entrySet()) {
                int n = (int) e.getValue()[1];
                double tot = e.getValue()[0];
                double mean = n > 0 ? tot / n : 0.0;
                w.write(String.format("%s,%d,%.6f,%.6f%n", e.getKey(), n, tot, mean));
            }
        } catch (IOException e) {
            log.error("ChargingTimeSavedAnalyzer iter " + iter + ": by-type CSV write failed", e);
        }

        // Histogram PNG (per-agent total time saved)
        try {
            String histPath = controlerIO.getIterationFilename(iter, "charging_time_saved_per_agent_histogram.png");
            writeAgentHistogram(byAgent, iter, histPath);
        } catch (Exception e) {
            log.error("ChargingTimeSavedAnalyzer iter " + iter + ": histogram render failed", e);
        }

        // Bar PNG (by charger type)
        try {
            String barPath = controlerIO.getIterationFilename(iter, "charging_time_saved_by_type_bar.png");
            writeTypeBar(byType, iter, barPath);
        } catch (Exception e) {
            log.error("ChargingTimeSavedAnalyzer iter " + iter + ": bar render failed", e);
        }

        // Master trajectory row
        double meanPerSession = nSessions > 0 ? totalSavedH / nSessions : 0.0;
        double[] perAgentTotals = new double[byAgent.size()];
        int k = 0;
        for (double[] v : byAgent.values()) perAgentTotals[k++] = v[0];
        Arrays.sort(perAgentTotals);
        double p50 = pct(perAgentTotals, 0.50);
        double p95 = pct(perAgentTotals, 0.95);
        double meanPerAgent = perAgentTotals.length > 0
                ? Arrays.stream(perAgentTotals).sum() / perAgentTotals.length
                : 0.0;

        appendMasterRow(iter, nSessions, totalSavedH, meanPerSession, p50, p95, meanPerAgent);

        log.info(String.format(
                "ChargingTimeSavedAnalyzer iter %d: n_sess=%d total_saved=%.2fh mean_per_sess=%.4fh "
                        + "p50_agent=%.4fh p95_agent=%.4fh",
                iter, nSessions, totalSavedH, meanPerSession, p50, p95));
    }

    // -------------------------------------------------- ShutdownListener

    @Override
    public void notifyShutdown(ShutdownEvent event) {
        if (masterCsv == null || !Files.exists(masterCsv)) return;
        try {
            renderTrajectory(masterCsv);
        } catch (Exception e) {
            log.error("ChargingTimeSavedAnalyzer: trajectory render failed", e);
        }
    }

    // -------------------------------------------------- helpers

    /** Read sessions CSV (semicolon-delimited per ChargingSessionStatsCollector). */
    private List<SessionRow> readSessions(Path csv) throws IOException {
        List<SessionRow> out = new ArrayList<>();
        try (BufferedReader br = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            String header = br.readLine();
            if (header == null) return out;
            String[] cols = header.split(";");
            Map<String, Integer> idx = new HashMap<>();
            for (int i = 0; i < cols.length; i++) idx.put(cols[i].trim().toLowerCase(), i);

            Integer iPerson  = idx.get("person_id");
            Integer iType    = idx.get("charger_type");
            Integer iEnergy  = idx.get("energy_kwh");
            Integer iEffKW   = idx.get("effective_charging_power_kw");  // optional

            if (iPerson == null || iType == null || iEnergy == null) {
                log.warn("ChargingTimeSavedAnalyzer: required columns missing in " + csv);
                return out;
            }

            String line;
            while ((line = br.readLine()) != null) {
                if (line.isEmpty()) continue;
                String[] a = line.split(";", -1);
                if (a.length <= Math.max(iPerson, Math.max(iType, iEnergy))) continue;
                SessionRow r = new SessionRow();
                r.personId    = a[iPerson];
                r.chargerType = a[iType];
                r.energyKwh   = parseD(a[iEnergy]);
                r.effectivePowerKW = (iEffKW != null && iEffKW < a.length) ? parseD(a[iEffKW]) : Double.NaN;
                out.add(r);
            }
        }
        return out;
    }

    private static double parseD(String s) {
        if (s == null) return Double.NaN;
        s = s.trim();
        if (s.isEmpty()) return Double.NaN;
        try { return Double.parseDouble(s); } catch (NumberFormatException e) { return Double.NaN; }
    }

    private static double pct(double[] sorted, double q) {
        if (sorted == null || sorted.length == 0) return 0.0;
        if (sorted.length == 1) return sorted[0];
        double pos = q * (sorted.length - 1);
        int lo = (int) Math.floor(pos);
        int hi = (int) Math.ceil(pos);
        if (lo == hi) return sorted[lo];
        double frac = pos - lo;
        return sorted[lo] * (1.0 - frac) + sorted[hi] * frac;
    }

    private void writeAgentHistogram(Map<String, double[]> byAgent, int iter, String outPng) throws Exception {
        double[] values = new double[byAgent.size()];
        int i = 0;
        for (double[] v : byAgent.values()) values[i++] = v[0];

        HistogramDataset ds = new HistogramDataset();
        ds.setType(HistogramType.FREQUENCY);
        ds.addSeries("agents", values, 30);

        JFreeChart chart = ChartFactory.createHistogram(
                "Per-Agent Total Time Saved vs L2 Baseline — iter " + iter,
                "Total time saved per agent (hours)",
                "Number of agents",
                ds,
                PlotOrientation.VERTICAL,
                true, false, false);
        savePng(chart, outPng, 1000, 600);
    }

    private void writeTypeBar(Map<String, double[]> byType, int iter, String outPng) throws Exception {
        DefaultCategoryDataset ds = new DefaultCategoryDataset();
        // Stable ordering: home, work, L2, DCFC, DCFC_TESLA, then anything else
        List<String> order = new ArrayList<>(Arrays.asList("home", "work", "L2", "DCFC", "DCFC_TESLA"));
        for (String t : byType.keySet()) if (!order.contains(t)) order.add(t);
        for (String t : order) {
            double[] v = byType.get(t);
            if (v == null) continue;
            ds.addValue(v[0], "total_time_saved_h", t + " (n=" + (int) v[1] + ")");
        }
        JFreeChart chart = ChartFactory.createBarChart(
                "Total Time Saved by Charger Type vs L2 Baseline — iter " + iter,
                "Charger type (n_sessions)",
                "Total time saved (hours)",
                ds,
                PlotOrientation.VERTICAL,
                true, true, false);
        savePng(chart, outPng, 1000, 600);
    }

    private synchronized void appendMasterRow(int iter, int nSessions, double totalSavedH,
                                              double meanPerSession, double p50, double p95,
                                              double meanPerAgent) {
        if (masterCsv == null) {
            // Anchor master CSV one level above ITERS/it.N/ (i.e. the run output dir).
            String anyIterPath = controlerIO.getIterationFilename(iter, "x.tmp");
            Path anyIter = Paths.get(anyIterPath).toAbsolutePath();
            // anyIter ~ <out>/ITERS/it.N/N.x.tmp -> two parents to <out>/ITERS, three to <out>.
            Path runOut = anyIter.getParent().getParent().getParent();
            if (runOut == null) runOut = Paths.get(".").toAbsolutePath();
            masterCsv = runOut.resolve("time_saved_by_iteration.csv");
        }
        boolean fresh = !Files.exists(masterCsv);
        try (BufferedWriter w = Files.newBufferedWriter(masterCsv,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            if (fresh) {
                w.write("iter,n_sessions_total,total_time_saved_h,"
                        + "mean_time_saved_h_per_session,p50_per_agent_h,p95_per_agent_h,"
                        + "mean_per_agent_h\n");
            }
            w.write(String.format("%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f%n",
                    iter, nSessions, totalSavedH, meanPerSession, p50, p95, meanPerAgent));
        } catch (IOException e) {
            log.error("ChargingTimeSavedAnalyzer: master CSV append failed", e);
        }
    }

    private void renderTrajectory(Path masterCsv) throws Exception {
        XYSeries series = new XYSeries("mean_time_saved_h_per_session");
        try (BufferedReader br = Files.newBufferedReader(masterCsv, StandardCharsets.UTF_8)) {
            String header = br.readLine();
            if (header == null) return;
            String[] hcols = header.split(",");
            int iIter = -1, iMean = -1;
            for (int i = 0; i < hcols.length; i++) {
                if (hcols[i].equals("iter")) iIter = i;
                if (hcols[i].equals("mean_time_saved_h_per_session")) iMean = i;
            }
            if (iIter < 0 || iMean < 0) return;
            String line;
            while ((line = br.readLine()) != null) {
                String[] a = line.split(",");
                if (a.length <= Math.max(iIter, iMean)) continue;
                try {
                    int it = Integer.parseInt(a[iIter].trim());
                    double m = Double.parseDouble(a[iMean].trim());
                    series.add(it, m);
                } catch (NumberFormatException ignored) { }
            }
        }
        XYSeriesCollection ds = new XYSeriesCollection();
        ds.addSeries(series);
        JFreeChart chart = ChartFactory.createXYLineChart(
                "Mean Time Saved Per Session — Trajectory",
                "Iteration",
                "Mean time saved (h/session)",
                ds,
                PlotOrientation.VERTICAL,
                true, false, false);
        XYPlot plot = chart.getXYPlot();
        plot.setRenderer(new XYLineAndShapeRenderer(true, true));
        Path outPng = masterCsv.getParent().resolve("time_saved_trajectory.png");
        savePng(chart, outPng.toString(), 1100, 600);
        log.info("ChargingTimeSavedAnalyzer: wrote trajectory plot " + outPng);
    }

    /** JFreeChart used both ChartUtils and ChartUtilities across versions. */
    private static void savePng(JFreeChart chart, String outPath, int w, int h) throws Exception {
        File out = new File(outPath);
        try {
            Class<?> c = Class.forName("org.jfree.chart.ChartUtils");
            c.getMethod("saveChartAsPNG", File.class, JFreeChart.class, int.class, int.class)
                    .invoke(null, out, chart, w, h);
        } catch (ClassNotFoundException e) {
            Class<?> c = Class.forName("org.jfree.chart.ChartUtilities");
            c.getMethod("saveChartAsPNG", File.class, JFreeChart.class, int.class, int.class)
                    .invoke(null, out, chart, w, h);
        }
    }

    // -------------------------------------------------- inner types

    private static class SessionRow {
        String personId;
        String chargerType;
        double energyKwh;
        double effectivePowerKW;  // NaN if not present in CSV
    }
}
