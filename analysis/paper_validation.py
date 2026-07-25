#!/usr/bin/env python3
"""
paper_validation.py — assemble the master validation-metrics table (CSV + Markdown +
LaTeX booktabs) and a validation-scorecard figure, in uniform TRB/TRD style.
Outputs -> paper/tables/ and paper/figures/.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pubfig as pf

ROOT = Path(__file__).resolve().parents[2]          # repo root
PAPER = ROOT / "paper"
(PAPER / "tables").mkdir(parents=True, exist_ok=True)
(PAPER / "figures").mkdir(parents=True, exist_ok=True)

# (category, metric, value, target/reference, quality)  quality: good|moderate|weak
ROWS = [
    ("Population synthesis", "Marginal distributions (mean TVD)", "0.021", "0 (14 attributes)", "good"),
    ("Population synthesis", "Joint associations (Cramér's V, |Δ|)", "0.023", "0", "good"),
    ("Population synthesis", "County population totals (Pearson r)", "1.000", "1.0 (24 counties)", "good"),
    ("Population synthesis", "Memorization (DCR share > train)", "0.489", "≈0.5 (no copying)", "good"),
    ("Trip generation", "Trip distance (TVD)", "0.022", "0", "good"),
    ("Trip generation", "Travel mode (TVD)", "0.019", "0", "good"),
    ("Trip generation", "Departure-hour (TVD)", "0.022", "0", "good"),
    ("Trip generation", "Daily VMT vs survey", "−1.1%", "0% (weighted survey)", "good"),
    ("EV assignment", "County EV counts (Pearson r)", "1.000", "1.0 (MVA-2026)", "good"),
    ("EV assignment", "Fleet total", "148,302", "148,359 (−0.04%)", "good"),
    ("EV assignment", "BEV share", "0.738", "0.738 (MVA)", "good"),
    ("EV assignment", "Income-selection gradient (monotone)", "0.5%→5.5%", "rising (Burra–Cirillo)", "good"),
    ("Charging behaviour", "Home-charging venue share", "78.0%", "≈80% (Hardman et al.)", "good"),
    ("Charging behaviour", "Public diurnal profile (Pearson r)", "0.818", "1.0 (ChargePoint agg.)", "good"),
    ("Charging behaviour", "Public peak-hour error", "1 h", "0 (ChargePoint)", "good"),
    ("Charging behaviour", "EV-WATTS SOC-swing (TVD, holdout)", "0.207", "0", "moderate"),
    ("Charging behaviour", "EV-WATTS session energy (TVD, holdout)", "0.315", "0 (national pop. caveat)", "moderate"),
    ("Charging behaviour", "Public utilization level", "7.5%", "13.8% (ChargePoint)", "weak"),
    ("Charging behaviour", "Per-station occupancy (median r)", "0.12", "1.0 (inherent limit)", "weak"),
    ("Robustness", "Charger shares across 3 seeds (SD)", "±0.001", "0 (Monte-Carlo)", "good"),
    ("Robustness", "Public share across 4-param sensitivity", "0.145–0.159", "stable", "good"),
    ("Robustness", "25% vs 100% venue share (certification)", "±0.002", "0 (sample scaling)", "good"),
    ("Fiscal outcome", "Shadow gas-tax gap R* (state)", "$33.3 M/yr", "MVA-anchored", "good"),
]

QCOL = {"good": pf.GREEN, "moderate": pf.ORANGE, "weak": pf.VERM}


def main():
    df = pd.DataFrame(ROWS, columns=["Category", "Metric", "Value", "Reference", "Quality"])
    df.to_csv(PAPER / "tables/validation_metrics.csv", index=False)

    # ---- Markdown ----
    md = ["# Master validation metrics — UrbanEV-Maryland 2026\n"]
    for cat in df.Category.unique():
        md.append(f"\n## {cat}\n\n| Metric | Value | Reference |\n|---|---|---|")
        for _, r in df[df.Category == cat].iterrows():
            md.append(f"| {r.Metric} | **{r.Value}** | {r.Reference} |")
    (PAPER / "tables/validation_metrics.md").write_text("\n".join(md))

    # ---- LaTeX booktabs ----
    tex = [r"\begin{table}[t]\centering",
           r"\caption{Validation summary for the Maryland 2026 synthetic EV population and "
           r"charging simulation. TVD = total variation distance; $r$ = Pearson correlation.}",
           r"\label{tab:validation}", r"\small", r"\begin{tabular}{lll}", r"\toprule",
           r"Metric & Value & Reference \\ \midrule"]
    for cat in df.Category.unique():
        tex.append(rf"\multicolumn{{3}}{{l}}{{\textit{{{cat}}}}} \\")
        for _, r in df[df.Category == cat].iterrows():
            esc = lambda s: str(s).replace("%", r"\%").replace("→", r"$\rightarrow$").replace("±", r"$\pm$").replace("−", "-").replace("$33.3", r"\$33.3").replace("Δ", r"$\Delta$").replace("≈", r"$\approx$").replace("é", "e")
            tex.append(rf"\quad {esc(r.Metric)} & {esc(r.Value)} & {esc(r.Reference)} \\")
        tex.append(r"\addlinespace")
    tex += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    (PAPER / "tables/validation_metrics.tex").write_text("\n".join(tex))

    # ---- Scorecard figure (numeric metrics only) ----
    num = []
    for _, r in df.iterrows():
        v = r.Value
        try:
            x = float(v.replace("%", "").replace("±", "").replace("−", "-").replace(",", "").split("–")[0].replace("$", "").replace(" M/yr", ""))
            if "%" in v and abs(x) > 2: x = abs(x) / 100  # rate-like %
            num.append((r.Metric[:42], x if x <= 1.2 else None, r.Quality))
        except Exception:
            pass
    tv = [(m, x, q) for m, x, q in num if x is not None and 0 <= x <= 1.05]
    tv = tv[::-1]
    fig, ax = pf.newfig(6.6, 7.2)
    ax.barh([m for m, _, _ in tv], [x for _, x, _ in tv],
            color=[QCOL[q] for _, _, q in tv], edgecolor="k", lw=0.3)
    ax.set(xlabel="metric value (TVD / correlation / share)",
           title="Validation scorecard")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=QCOL["good"], label="strong"),
                       Patch(color=QCOL["moderate"], label="moderate"),
                       Patch(color=QCOL["weak"], label="limitation")], loc="lower right")
    pf.save(fig, PAPER / "figures", "validation_scorecard")
    print(f"[done] master table (csv/md/tex) + scorecard -> {PAPER}")
    print(df.groupby("Quality").size().to_dict())


if __name__ == "__main__":
    main()
