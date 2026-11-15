"""Tables, figures and LaTeX macros for the paper's evaluation, generated from docs/paper/research.json.

    uv run python scripts/research_assets.py [path/to/research.json]

Nothing in the evaluation section of the paper is typed by hand: every number comes from this script.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / "paper"
FIG, TAB = PAPER / "figures", PAPER / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else PAPER / "research.json"
R = json.loads(SRC.read_text(encoding="utf-8"))
AUDIT = PAPER / "data_audit.json"

BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#898781", "#e1e0d9"
plt.rcParams.update({
    "font.family": "serif", "font.size": 8.5, "axes.edgecolor": "#9a998f", "axes.linewidth": 0.7,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.labelcolor": "#2b2a27", "figure.dpi": 200, "savefig.bbox": "tight", "legend.frameon": False,
})

macros: dict[str, str] = {}


def m(name: str, value) -> None:
    assert name.isalpha(), name
    macros[name] = str(value)


def ok(x) -> bool:
    return x is not None and np.isfinite(x)


def f1(x):
    return f"{x:.1f}".replace("-", "$-$") if ok(x) else "--"


def f2(x):
    return f"{x:.2f}".replace("-", "$-$") if ok(x) else "--"


def f3(x):
    return f"{x:.3f}".replace("-", "$-$") if ok(x) else "--"


def sgn(x, d=2):
    return (f"{x:+.{d}f}".replace("-", "$-$")) if ok(x) else "--"


def pv(p):
    """p-value with its relation, for running text: $p\\Macro$ renders as p = 0.019 or p < 0.001."""
    if not ok(p):
        return "=\\text{--}"
    return "<0.001" if p < 0.001 else f"={p:.3f}"


def pc(x, d=0):
    return f"{x * 100:.{d}f}\\%"


def sp(x, d=0):
    return ("$-$" if x < 0 else "") + pc(abs(x), d)


def stars(p):
    return "" if not ok(p) else ("$^{***}$" if p < 0.01 else "$^{**}$" if p < 0.05 else "$^{*}$" if p < 0.1 else "")


def diff(d, digits=2):
    return "" if not d else f"{sgn(d['diff'], digits)}{stars(d['p'])}"


def ci_txt(c, d=2):
    return f"[{f'{c[0]:.{d}f}'.replace('-', '$-$')}, {f'{c[1]:.{d}f}'.replace('-', '$-$')}]" if c else ""


def big(n):
    return f"{n:,}".replace(",", "{,}")


def table(name: str, lines: list[str]) -> None:
    (TAB / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


NAMES = {
    "twin": "Twin: stress health score", "twin_base": "Twin: baseline health score", "twin_pb": "Twin: breach probability",
    "twin_rec": "Twin: recession health score", "formula": "Health formula, no simulation", "altman_z2": "Altman Z$''$",
    "ohlson_o": "Ohlson O-score", "zmijewski": "Zmijewski score", "icr": "Interest coverage",
    "nd_ebitda": "Net debt / EBITDA", "cash_rev": "Cash / revenue", "current_ratio": "Current ratio",
    "static_stress": "Static stress test", "rev_vol": "Revenue volatility", "fixed_share": "Fixed-cost share",
    "size": "Size (log revenue)", "fcf_margin": "Trailing FCF margin", "capex_rev": "Capex / revenue",
}
CLASSIC = ["altman_z2", "ohlson_o", "zmijewski", "icr", "nd_ebitda", "cash_rev", "current_ratio", "static_stress",
           "rev_vol", "fixed_share", "size"]
CASHFLOW = ["fcf_margin", "capex_rev"]
MODEL = {"N1": "Margin, 4 quarters", "N2": "Margin, 8 quarters", "N3": "Margin, 16 quarters",
         "N4": "Margin shrunk to industry", "N5": "Cash = $a + b\\cdot$revenue", "N6": "Regression + change in revenue",
         "T0": "Twin without loops", "T1": "Twin"}


def lower(name):
    return name if name.split()[0] in ("Altman", "Ohlson", "Zmijewski") else name[0].lower() + name[1:]


m("NBench", len(CLASSIC) + len(CASHFLOW))
smp = R["samples"]
m("PanFirmYears", big(smp["panel_firm_years"]))
m("PanFirms", big(smp["panel_firms"]))
m("CovEdgarN", big(smp["covid"]["edgar"]))
m("CovSpN", smp["covid"]["sp2020"])
u = (ROOT / "engine" / "fintwin" / "data" / "universe_edgar.csv").read_text(encoding="utf-8").splitlines()
m("UniverseN", big(len(u) - 1))
m("UniverseBk", sum(1 for line in u[1:] if line.rstrip().split(",")[-1]))

# ------------------------------------------------------------------ 1. transmission (primary)
T = R["transmission"]["panel"]
m("TrN", big(T["n"]))
m("TrFirms", big(T["n_firms"]))
cfo, fcf = T["cfo"], T["fcf"]
lv, inc = cfo["levels"], cfo["incremental"]
for k in MODEL:
    m(f"TrMae{k.replace('1', 'one').replace('2', 'two').replace('3', 'three').replace('4', 'four').replace('5', 'five').replace('6', 'six').replace('0', 'zero')}",
      f1(lv[k]["median_ae"]))
m("TrIncrTwin", f2(inc["N1"]["T1"]["rho"]))
m("TrIncrTwinLo", f2(inc["N1"]["T1"]["ci"][0]))
m("TrIncrTwinHi", f2(inc["N1"]["T1"]["ci"][1]))
m("TrIncrSixteen", f2(inc["N1"]["N3"]["rho"]))
m("TrIncrSixteenLo", f2(inc["N1"]["N3"]["ci"][0]))
m("TrIncrSixteenHi", f2(inc["N1"]["N3"]["ci"][1]))
m("TrIncrShrunk", f2(inc["N1"]["N4"]["rho"]))
m("TrIncrReg", f2(inc["N1"]["N6"]["rho"]))
m("TrIncrEight", f2(inc["N1"]["N2"]["rho"]))
m("TrTwinVsSixteen", f2(inc["N3"]["T1"]["rho"]))
m("TrTwinVsSixteenLo", f2(inc["N3"]["T1"]["ci"][0]))
m("TrTwinVsSixteenHi", f2(inc["N3"]["T1"]["ci"][1]))
m("TrFourVsSixteen", f2(inc["N3"]["N1"]["rho"]))
m("TrTwinVsShrunk", f2(inc["N4"]["T1"]["rho"]))
m("TrTwinVsShrunkLo", f2(inc["N4"]["T1"]["ci"][0]))
m("TrTwinVsShrunkHi", f2(inc["N4"]["T1"]["ci"][1]))
m("TrTwinVsReg", f2(inc["N6"]["T1"]["rho"]))
m("TrTwinVsRegLo", f2(inc["N6"]["T1"]["ci"][0]))
m("TrTwinVsRegHi", f2(inc["N6"]["T1"]["ci"][1]))
enc2 = cfo["encompassing"]
if "all_two_way" in enc2:
    m("TrEncTwinTTwoWay", f1(enc2["all_two_way"]["t"]["T1"]))
    m("TrEncShrunkTTwoWay", f1(enc2["all_two_way"]["t"]["N4"]))
    m("TrEncLevelsTwinTTwoWay", f1(enc2["levels"]["t_two_way"]["T1"]))
    h = enc2["hln"]
    m("TrHlnTwinOverSixteen", f1(h["T1_encompasses_N3"]["t"]))
    m("TrHlnSixteenOverTwin", f1(h["N3_encompasses_T1"]["t"]))
    m("TrHlnTwinOverReg", f1(h["T1_encompasses_N6"]["t"]))
    m("TrHlnRegOverTwin", f1(h["N6_encompasses_T1"]["t"]))
m("TrFcfTwinVsSixteen", f2(fcf["incremental"]["N3"]["T1"]["rho"]))
enc = cfo["encompassing"]["all"]
m("TrEncTwinCoef", f2(enc["coef"]["T1"]))
m("TrEncTwinT", f1(enc["t"]["T1"]))
m("TrEncSixteenT", f1(enc["t"]["N3"]))
m("TrEncShrunkT", f1(enc["t"]["N4"]))
m("TrEncRegT", f1(enc["t"]["N6"]))
m("TrEncFcfTwinT", f1(fcf["encompassing"]["all"]["t"]["T1"]))
lev_e = cfo["encompassing"]["levels"]
m("TrEncLevTwinT", f1(lev_e["t"]["T1"]))
m("TrEncLevTwinCoef", f2(lev_e["coef"]["T1"]))
m("TrEncLevFcfTwinT", f1(fcf["encompassing"]["levels"]["t"]["T1"]))
m("TrVerdict", "survives" if T["verdict"]["transmission_claim_survives"] else "fails")
hy = cfo["hybrid"]
m("TrHybN", big(hy["n"]))
m("TrHybSixteen", f2(hy["mae_w"]["N3"]))
m("TrHybSixteenTwin", f2(hy["mae_w"]["N3+T1"]))
m("TrHybSixteenReg", f2(hy["mae_w"]["N3+N6"]))
m("TrHybTwin", f2(hy["mae_w"]["T1"]))
m("TrHybGain", f2(-hy["N3+T1_vs_N3"]["diff"]))
m("TrHybDollar", f"{-hy['N3+T1_vs_N3']['diff'] * 100:.0f}")  # $ million per $10 billion of trailing revenue
m("TrNRound", f"{round(T['n'], -3):,}".replace(",", "{,}"))
m("TrHybGainLo", f2(-hy["N3+T1_vs_N3"]["ci"][1]))
m("TrHybGainHi", f2(-hy["N3+T1_vs_N3"]["ci"][0]))
m("TrHybGainPct", pc(-hy["N3+T1_vs_N3"]["diff"] / hy["mae_w"]["N3"], 1))
m("TrHybVsNull", f2(-hy["N3+T1_vs_N3+N6"]["diff"]))
m("TrHybVsNullP", pv(hy["N3+T1_vs_N3+N6"]["p"]))
m("TrHybSixteenRegFive", f2(hy["mae_w"]["N3+N5"]))
m("TrHybVsRegFive", f2(-hy["N3+T1_vs_N3+N5"]["diff"]))
m("TrHybVsRegFiveP", pv(hy["N3+T1_vs_N3+N5"]["p"]))
m("TrHybVsFour", f2(-hy["N3+T1_vs_N3+N1"]["diff"]))
m("TrHybVsFourP", pv(hy["N3+T1_vs_N3+N1"]["p"]))
m("TrHybRegFiveGainPct", pc((hy["mae_w"]["N3"] - hy["mae_w"]["N3+N5"]) / hy["mae_w"]["N3"], 1))
lams = list(hy["lambda"]["N3+T1"].values())
m("TrLambdaLo", f2(min(lams)))
m("TrLambdaHi", f2(max(lams)))
fhy = fcf["hybrid"]
m("TrFcfHybGainPct", pc(-fhy["N3+T1_vs_N3"]["diff"] / fhy["mae_w"]["N3"], 1))
best_null_fcf = min(("N3+N1", "N3+N2", "N3+N5", "N3+N6"), key=lambda k: fhy["mae_w"][k])
m("TrFcfVsBestNull", f2(-fhy[f"N3+T1_vs_{best_null_fcf}"]["diff"]))
m("TrFcfVsBestNullLo", f2(-fhy[f"N3+T1_vs_{best_null_fcf}"]["ci"][1]))
m("TrFcfVsBestNullHi", f2(-fhy[f"N3+T1_vs_{best_null_fcf}"]["ci"][0]))
m("TrFcfVsBestNullP", pv(fhy[f"N3+T1_vs_{best_null_fcf}"]["p"]))
m("TrFcfVsWorstP", pv(max(fhy[f"N3+T1_vs_{k}"]["p"] for k in ("N3+N1", "N3+N2", "N3+N5", "N3+N6"))))

rows = []
for k, label in MODEL.items():
    a, b = cfo["levels"][k], fcf["levels"][k]
    i1 = inc["N1"].get(k, {})
    i3 = inc["N3"].get(k, {})
    rows.append(f"{label} & {f1(a['median_ae'])} & {f1(a['mae_w'])} & {f2(a['rho'])} & "
                f"{f2(i1.get('rho')) if k != 'N1' else ''} {ci_txt(i1.get('ci'))} & "
                f"{f2(i3.get('rho')) if k != 'N3' else ''} {ci_txt(i3.get('ci'))} & {f1(b['median_ae'])} & "
                f"{f2(fcf['incremental']['N3'].get(k, {}).get('rho')) if k != 'N3' else ''} \\\\")
    if k in ("N4", "N6"):
        rows.append("\\addlinespace")
table("transmission", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrllrr}", "\\toprule",
    " & \\multicolumn{5}{c}{Operating cash flow} & \\multicolumn{2}{c}{Free cash flow} \\\\",
    "\\cmidrule(lr){2-6}\\cmidrule(lr){7-8}",
    " & \\multicolumn{2}{c}{Error (pp of revenue)} & & \\multicolumn{2}{c}{Incremental $\\rho$ against} & Median & Incr.\\ $\\rho$ \\\\",
    "\\cmidrule(lr){2-3}\\cmidrule(lr){5-6}",
    "Model & Median & Mean & $\\rho$ & 4-quarter margin [95\\% CI] & 16-quarter margin [95\\% CI] & error & vs.\\ 16q \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])

rows = []
for var, lab in (("cfo", "Operating cash flow"), ("fcf", "Free cash flow")):
    e = T[var]["encompassing"]
    cells = []
    specs = ("twin_only", "nulls_only", "all", "levels_nulls_only", "levels")
    for spec in specs:
        x = e[spec]
        cells.append(" & ".join(
            f"{f2(x['coef'][k])} ({f1(x['t'][k])}){stars(x['p'][k])}" if k in x["coef"] else ""
            for k in ("N1", "T1", "N3", "N4", "N6")
        ) + f" & {f2(x['r2'])}")
    labels = ("Departures: twin only", "Departures: simple rules only", "Departures: all",
              "Levels: simple rules only", "Levels: all")
    for spec, c in zip(labels, cells, strict=True):
        rows.append(f"{lab if spec.endswith('twin only') else ''} & {spec} & {c} \\\\")
    rows.append("\\addlinespace")
table("encompassing", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{llrrrrrr}", "\\toprule",
    "Cash measure & Specification & 4q margin & Twin & 16q margin & Shrunk margin & Regression + timing & $R^2$ \\\\",
    "\\midrule",
    *rows[:-1], "\\bottomrule", "\\end{tabular}}"])

HYB = [("N1", "Margin, 4 quarters"), ("N3", "Margin, 16 quarters"), ("N6", "Regression + revenue change"),
       ("T1", "Twin alone"), ("N1+T1", "4-quarter margin + $\\lambda$(twin $-$ rule)"),
       ("N3+N1", "16-quarter margin + $\\lambda$(4-quarter margin $-$ rule)"),
       ("N3+N5", "16-quarter margin + $\\lambda$(regression $-$ rule)"),
       ("N3+N6", "16-quarter margin + $\\lambda$(regression with timing $-$ rule)"),
       ("N3+T1", "16-quarter margin + $\\lambda$(twin $-$ rule)")]
rows = []
for k, lab in HYB:
    rows.append(f"{lab} & {f2(hy['mae_w'][k])} & {f2(hy['median_ae'][k])} & {f2(fhy['mae_w'][k])} & "
                f"{f2(fhy['median_ae'][k])} \\\\")
cmp_rows = []
for a, b, lab in (("N3+T1", "N3", "16q margin + twin vs.\\ 16q margin"),
                  ("N3+T1", "N3+N1", "16q margin + twin vs.\\ 16q margin + 4q margin"),
                  ("N3+T1", "N3+N5", "16q margin + twin vs.\\ 16q margin + regression"),
                  ("N3+T1", "N3+N6", "16q margin + twin vs.\\ 16q margin + regression with timing"),
                  ("N1+T1", "N1", "4q margin + twin vs.\\ 4q margin"), ("T1", "N3", "Twin vs.\\ 16q margin")):
    x, y = hy[f"{a}_vs_{b}"], fhy[f"{a}_vs_{b}"]
    cmp_rows.append(f"{lab} & \\multicolumn{{2}}{{r}}{{{sgn(x['diff'])} {ci_txt(x['ci'])}{stars(x['p'])}}} & "
                    f"\\multicolumn{{2}}{{r}}{{{sgn(y['diff'])} {ci_txt(y['ci'])}{stars(y['p'])}}} \\\\")
table("hybrid", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrr}", "\\toprule",
    " & \\multicolumn{2}{c}{Operating cash flow} & \\multicolumn{2}{c}{Free cash flow} \\\\",
    "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}",
    "Out-of-sample prediction & Mean error & Median error & Mean error & Median error \\\\", "\\midrule", *rows,
    "\\midrule", "\\multicolumn{5}{l}{\\emph{Difference in mean error (negative: the first is better), firm-clustered CI}} \\\\",
    *cmp_rows, "\\bottomrule", "\\end{tabular}}"])

HET = {"leverage": "Net debt / EBITDA", "fixed_costs": "Fixed-cost share", "maturities": "Debt due / cash",
       "revenue_shock": "Revenue over the window"}
rows = []
for g, lab in HET.items():
    first = True
    for lev, c in cfo["heterogeneity"][g].items():
        lev_tex = lev.replace("%", "\\%").replace(">", "$>$")  # kept out of the f-string: backslashes there need Python 3.12
        rows.append(f"{lab if first else ''} & {lev_tex} & {big(c['n'])} & {f2(c['T1|N1'])} & "
                    f"{f2(c['N3|N1'])} & {f2(c['T1|N6'])} & {f1(c['mae_N1'])} & {f1(c['mae_T1'])} \\\\")
        first = False
    rows.append("\\addlinespace")
table("heterogeneity", [
    "\\begin{tabular}{llrrrrrr}", "\\toprule",
    " & & & \\multicolumn{3}{c}{Incremental $\\rho$} & \\multicolumn{2}{c}{Median error} \\\\",
    "\\cmidrule(lr){4-6}\\cmidrule(lr){7-8}",
    "Split by & Group & Firm-years & Twin vs.\\ 4q & 16q vs.\\ 4q & Twin vs.\\ regr. & 4q margin & Twin \\\\",
    "\\midrule", *rows[:-1], "\\bottomrule", "\\end{tabular}"])
down = cfo["heterogeneity"]["revenue_shock"]["fell >10%"]
m("HetDownN", big(down["n"]))
m("HetDownTwin", f2(down["T1|N1"]))
m("HetDownSixteen", f2(down["N3|N1"]))
hl = cfo["heterogeneity"]["leverage"]
m("HetLevHighTwinReg", f2(hl["high"]["T1|N6"]))
m("HetLevLowTwinReg", f2(hl["low"]["T1|N6"]))

# ------------------------------------------------------------------ 2. liquidity decisions and loops
DEC = {"cash_half": "Cash falls below half", "debt_raise": "New borrowing $>$ 5\\% of revenue",
       "div_cut": "Dividend cut by half", "capex_cut": "Capex cut by a quarter"}
rows, arows = [], []
for e, lab in DEC.items():
    d = T["decisions"][e]
    o = d["oos"]
    dd = o["delta_twin"]
    rows.append(f"{lab} & {big(d['n'])} & {pc(d['base_rate'])} & {f2(d['auc']['twin'])} & {f2(d['auc']['static'])} & "
                f"{f2(d['auc']['formula'])} & {f2(d['auc']['fcf_margin'])} & {f2(o['auc']['rule_score'])} & "
                f"{f2(o['auc']['rule_score_twin'])} & {sgn(dd['diff'], 3)} {ci_txt(dd['ci'], 3)}{stars(dd['p'])} \\\\")
    arows.append(f"{lab} & {f2(d['auc']['twin'])} & " + " & ".join(
        f"{f2(d['auc'][a])}{stars(d['twin_minus'][a]['p'])}" for a in ("no_r1", "no_r2", "no_b1", "no_b2", "no_loops")) + " \\\\")
table("decisions", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrrrrrrl}", "\\toprule",
    " & & & \\multicolumn{4}{c}{Univariate AUC} & \\multicolumn{3}{c}{Out-of-sample logit AUC} \\\\",
    "\\cmidrule(lr){4-7}\\cmidrule(lr){8-10}",
    "Event in the next 8 quarters & Firm-years & Rate & Twin & Static runway & Formula & FCF margin & "
    "Rule + scores & + Twin & $\\Delta$ [95\\% CI] \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])
table("loops", [
    "\\begin{tabular}{lrrrrrr}", "\\toprule",
    "Event & Full twin & No R1 & No R2 & No B1 & No B2 & No loops \\\\", "\\midrule", *arows,
    "\\bottomrule", "\\end{tabular}"])
dc = T["decisions"]
m("DecCapexDelta", f3(dc["capex_cut"]["oos"]["delta_twin"]["diff"]))
m("DecCashDelta", f3(dc["cash_half"]["oos"]["delta_twin"]["diff"]))
m("DecDebtDelta", f3(dc["debt_raise"]["oos"]["delta_twin"]["diff"]))
m("DecDivDelta", f3(dc["div_cut"]["oos"]["delta_twin"]["diff"]))
m("DecCashTwin", f2(dc["cash_half"]["auc"]["twin"]))
m("DecCashNoRtwo", f2(dc["cash_half"]["auc"]["no_r2"]))
m("DecCapexTwin", f2(dc["capex_cut"]["auc"]["twin"]))
m("DecCapexStatic", f2(dc["capex_cut"]["auc"]["static"]))
m("DecCapexNoBone", f2(dc["capex_cut"]["auc"]["no_b1"]))

# ------------------------------------------------------------------ 3. sensitivity
SENS = {"baseline": "As specified", "revolver_low": "Credit line 4\\% of revenue (untagged)",
        "revolver_high": "Credit line 15\\% of revenue (untagged)", "fixed_prior_low": "Fixed-cost prior 20\\%",
        "fixed_prior_high": "Fixed-cost prior 50\\%", "prior_weak": "Prior weight 0.5 (data dominate)",
        "prior_strong": "Prior weight 8 (prior dominates)", "no_shrinkage": "No shrinkage of growth and cyclicality",
        "access_strict": "Market access cut below 2.5$\\times$ / 1.5$\\times$ coverage",
        "access_lenient": "Market access cut below 1.0$\\times$ / 0.5$\\times$, milder cuts",
        "cuts_fast": "Faster, deeper restructuring", "spreads_pit": "Rating spreads at the cutoff's Baa spread",
        "spreads_2026": "January 2026 rating table (as in the product)",
        "spreads_baa": "2026 table rescaled by the cutoff's Baa spread"}
S = T["sensitivity"]
rows = [f"{lab} & {f1(S[k]['median_ae'])} & {f2(S[k]['incr_N1'])} & {f2(S[k]['incr_N6'])} & {f2(S[k]['auc_bk'])} & "
        f"{f2(S[k]['auc_burn'])} \\\\" for k, lab in SENS.items() if k in S]
rows.insert(1, "\\addlinespace")
table("sensitivity", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrrr}", "\\toprule",
    " & Median error & \\multicolumn{2}{c}{Incremental $\\rho$ against} & \\multicolumn{2}{c}{Baseline score AUC} \\\\",
    "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}",
    "Assumption & (pp of revenue) & 4q margin & regression & Bankruptcy & Severe burn \\\\", "\\midrule", *rows,
    "\\bottomrule", "\\end{tabular}}"])
alt = [k for k in S if k != "baseline"]
m("SensIncrLo", f2(min(S[k]["incr_N1"] for k in alt)))
m("SensIncrHi", f2(max(S[k]["incr_N1"] for k in alt)))
m("SensBkLo", f2(min(S[k]["auc_bk"] for k in alt)))
m("SensBkHi", f2(max(S[k]["auc_bk"] for k in alt)))
m("SensMaeLow", f1(S["fixed_prior_low"]["median_ae"]))
m("SensMaeHigh", f1(S["fixed_prior_high"]["median_ae"]))

# ------------------------------------------------------------------ 4. bankruptcies on the census
BP, B20 = R["bankruptcy_panel"], R["bankruptcy_2020"]
m("BkPanN", big(BP["all"]["n"]))
m("BkPanEv", BP["all"]["events"])
m("BkWeakN", big(BP["weak"]["n"]))
m("BkWeakEv", BP["weak"]["events"])
m("BkWeakShare", pc(BP["weak"]["share_of_events"]))
if "distinct_firms" in BP:
    m("BkPanFirms", big(BP["distinct_firms"]))
if "four_quarters" in BP:
    q4 = BP["four_quarters"]
    m("BkFourEv", q4["events"])
    for k, tag in (("twin", "Twin"), ("formula", "Formula"), ("ohlson_o", "Ohlson"), ("altman_z2", "Altman")):
        m(f"BkFour{tag}", f2(q4["predictors"][k]["auc"]))
m("BkTwentyN", big(B20["all"]["n"]))
m("BkTwentyEv", B20["all"]["events"])
for blk, tag in ((BP["all"], "Pan"), (BP["weak"], "Weak"), (B20["all"], "Twenty"), (B20["weak"], "TwentyWeak")):
    p = blk["predictors"]
    twin_key = "twin_base" if tag in ("Pan", "Weak") and "twin_base" in p else "twin"
    m(f"Bk{tag}Twin", f2(p["twin"]["auc"]))
    m(f"Bk{tag}Formula", f2(p["formula"]["auc"]))
    m(f"Bk{tag}Altman", f2(p["altman_z2"]["auc"]))
    m(f"Bk{tag}Ohlson", f2(p["ohlson_o"]["auc"]))
    m(f"Bk{tag}Fcf", f2(p["fcf_margin"]["auc"]))
    m(f"Bk{tag}Size", f2(p["size"]["auc"]))
    m(f"Bk{tag}FormulaDiff", sgn(p["formula"]["twin_minus"]["diff"], 3))
    m(f"Bk{tag}FormulaP", pv(p["formula"]["twin_minus"]["p"]))
    del twin_key
BKNAME = {"twin": "Twin: health score (panel: baseline; 2020: stress)"}
ORDER_BK = ["twin", "twin_pb", "formula", *CLASSIC, *CASHFLOW]
rows = []
for k in ORDER_BK:
    cells = []
    for blk in (BP["all"], BP["weak"], B20["all"], B20["weak"]):
        v = blk["predictors"].get(k)
        cells.append(f"{f2(v['auc'])} {ci_txt(v['auc_ci'])}" if v else "--")
    rows.append(f"{BKNAME.get(k, NAMES[k])} & " + " & ".join(cells) + " \\\\")
    if k in ("formula", "size"):
        rows.append("\\addlinespace")
table("bankruptcy", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lllll}", "\\toprule",
    " & \\multicolumn{2}{c}{Panel 2014--2024, within 8 quarters} & \\multicolumn{2}{c}{20 Feb 2020, to end-2021} \\\\",
    "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}",
    f" & All ({BP['all']['events']} events) & Already weak ({BP['weak']['events']}) & All ({B20['all']['events']}) & "
    f"Already weak ({B20['weak']['events']}) \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])

# ------------------------------------------------------------------ 5. distress panel (other events)
P = R["panel"]
EV = {"severe_burn": "Severe cash burn", "abnormal_burn": "Severe abnormal burn",
      "coverage_collapse": "Coverage collapse", "dividend_cut": "Dividend cut", "bankruptcy": "Bankruptcy petition"}
rows = []
for ev, label in EV.items():
    e = P[ev]
    uni = e["univariate"]
    bb = max((k for k in [*CLASSIC, *CASHFLOW] if k in uni), key=lambda k: uni[k]["auc"])
    o = e["out_of_sample"]
    dd = o["delta_twin_beyond_formula"]
    rows.append(f"{label} & {big(e['n'])} & {big(e['events'])} & {f2(uni['twin']['auc'])} & {f2(uni['formula']['auc'])} & "
                f"{f2(uni[bb]['auc'])} ({lower(NAMES[bb])}) & {f2(o['benchmarks_formula']['auc'])} & "
                f"{f2(o['benchmarks_formula_twin']['auc'])} & {sgn(dd['diff'], 3)} {ci_txt(dd['ci'], 3)}{stars(dd['p'])} \\\\")
table("panel", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrrlrrl}", "\\toprule",
    " & & & \\multicolumn{3}{c}{Univariate AUC} & \\multicolumn{3}{c}{Out-of-sample logit AUC} \\\\",
    "\\cmidrule(lr){4-6}\\cmidrule(lr){7-9}",
    "Event (next 8 quarters) & Firm-years & Events & Twin & Formula & Best benchmark & Benchmarks & + Twin & $\\Delta$ [95\\% CI] \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])
sb = P["severe_burn"]
m("PanTwinAuc", f2(sb["univariate"]["twin"]["auc"]))
m("PanFcfAuc", f2(sb["univariate"]["fcf_margin"]["auc"]))
m("PanOosDelta", sgn(sb["out_of_sample"]["delta_twin_beyond_formula"]["diff"], 3))
m("PanAbnTwinAuc", f2(P["abnormal_burn"]["univariate"]["twin"]["auc"]))
m("PanOosYears", f"{sb['out_of_sample']['test_years'][0]}--{sb['out_of_sample']['test_years'][-1]}")

# ------------------------------------------------------------------ 6. 2020 as one stress episode
C, CA, EX = R["covid"], R["covid_abnormal"], R["exposure"]
rows = []
for k in ["twin", "twin_base", "formula", *CLASSIC, *CASHFLOW]:
    cells = []
    for s in ("edgar", "sp2020"):
        a, b = C[s]["predictors"].get(k), CA[s]["predictors"].get(k)
        cells += [f2(a["rho"]) if a else "--", f2(b["rho"]) if b else "--"]
    rows.append(f"{NAMES[k]} & " + " & ".join(cells) + " \\\\")
    if k in ("formula", "size"):
        rows.append("\\addlinespace")
table("covid", [
    "\\begin{tabular}{lrrrr}", "\\toprule",
    f" & \\multicolumn{{2}}{{c}}{{All filers ($n$ = {big(C['edgar']['n'])})}} & "
    f"\\multicolumn{{2}}{{c}}{{S\\&P 500 on 20 Feb 2020 ($n$ = {C['sp2020']['n']})}} \\\\",
    "\\cmidrule(lr){2-3}\\cmidrule(lr){4-5}",
    " & Raw burn & Abnormal burn & Raw burn & Abnormal burn \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"])
for s, tag in (("edgar", "All"), ("sp2020", "Sp")):
    cp, ca = C[s]["predictors"], CA[s]["predictors"]
    m(f"Cov{tag}N", big(C[s]["n"]))
    m(f"Cov{tag}Twin", f2(cp["twin"]["rho"]))
    m(f"Cov{tag}Altman", f2(cp["altman_z2"]["rho"]))
    m(f"Cov{tag}Fcf", f2(cp["fcf_margin"]["rho"]))
    m(f"Cov{tag}Formula", f2(cp["formula"]["rho"]))
    m(f"Cov{tag}AbnTwin", f2(ca["twin"]["rho"]))
    m(f"Cov{tag}AbnFcf", f2(ca["fcf_margin"]["rho"]))
    m(f"Cov{tag}AbnRevVol", f2(ca["rev_vol"]["rho"]))
m("CovSpTodayTwin", f2(C["sp_today"]["predictors"]["twin"]["rho"]))
rows = []
for o, lab in (("real_burn", "Raw burn"), ("real_abn_burn", "Abnormal burn")):
    x = EX[o]
    rg = x.get("regression_robust") or x["regression"]
    fo = f"{f2(rg['formula']['coef'])} ({f1(rg['formula']['t'])})" if "formula" in rg else "--"
    rows.append(f"{lab} & {f2(x['twin_uniform']['rho'])} & {f2(x['exposure_only']['rho'])} & "
                f"{f2(x['twin_at_exposure']['rho'])} & {f2(x['fcf_margin']['rho'])} & "
                f"{f2(rg['exp']['coef'])} ({f1(rg['exp']['t'])}) & {f2(rg['twin']['coef'])} ({f1(rg['twin']['t'])}) & "
                f"{f2(rg['fcf']['coef'])} ({f1(rg['fcf']['t'])}) & {fo} \\\\")
table("exposure", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrrrrrr}", "\\toprule",
    " & \\multicolumn{4}{c}{Spearman $\\rho$ with burn} & \\multicolumn{4}{c}{Rank regression, coefficient ($t$)} \\\\",
    "\\cmidrule(lr){2-5}\\cmidrule(lr){6-9}",
    "Outcome & Twin, uniform freeze & Industry shock alone & Twin at industry shock & FCF margin & "
    "Industry shock & Twin at shock & FCF margin & Formula \\\\", "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])
m("ExpDepth", pc(EX["median_depth"]))
m("ExpTwinRaw", f2(EX["real_burn"]["twin_at_exposure"]["rho"]))
m("ExpUniformRaw", f2(EX["real_burn"]["twin_uniform"]["rho"]))
m("ExpOnlyAbn", f2(EX["real_abn_burn"]["exposure_only"]["rho"]))
m("ExpTwinAbn", f2(EX["real_abn_burn"]["twin_at_exposure"]["rho"]))
_rg = EX["real_abn_burn"].get("regression_robust") or EX["real_abn_burn"]["regression"]
m("ExpTwinAbnT", f1(_rg["twin"]["t"]))
m("ExpFcfAbnT", f1(_rg["fcf"]["t"]))
if "formula" in _rg:
    m("ExpFormulaAbnT", f1(_rg["formula"]["t"]))

# ------------------------------------------------------------------ 7. forecasts and calibration
FC, CAL = R["forecasts"], R["calibration"]
rows = []
for var, label in (("revenue", "Revenue"), ("cash_like", "Cash and short-term investments")):
    v = FC[var]
    cells = []
    for b in ("rw", "ets"):
        x = v[b]
        cells.append(f"{sp(x['skill_scaled'])} & {pc(x['share_better'])} & {f2(x['dm_t'])}")
    rows.append(f"{label} & {big(v['n'])} & {v['n_firms']} & " + " & ".join(cells) + " \\\\")
table("forecasts", [
    "\\begin{tabular}{lrrrrrrrr}", "\\toprule",
    " & & & \\multicolumn{3}{c}{vs.\\ seasonal random walk} & \\multicolumn{3}{c}{vs.\\ ETS} \\\\",
    "\\cmidrule(lr){4-6}\\cmidrule(lr){7-9}",
    " & Pairs & Firms & Skill & Better & DM $t$ & Skill & Better & DM $t$ \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}"])
fr, fcash = FC["revenue"], FC["cash_like"]
m("FcRevN", big(fr["n"]))
m("FcFirms", fr["n_firms"])
m("FcRevRw", sp(fr["rw"]["skill_scaled"]))
m("FcRevEts", sp(fr["ets"]["skill_scaled"]))
m("FcRevRwT", f2(fr["rw"]["dm_t"]))
m("FcRevEtsT", f2(fr["ets"]["dm_t"]))
m("FcCashRw", sp(fcash["rw"]["skill_scaled"]))
m("FcCashEts", sp(fcash["ets"]["skill_scaled"]))
rows = []
for var, lab in (("revenue", "Revenue"), ("cash_like", "Cash")):
    c = CAL[var]
    st = c["by"]["stress_2020"]
    s20, oth = st["2020Q2-2021Q1 targets"], st["other targets"]
    hz = c["by"]["horizon"]
    sz = c["by"]["size"]
    rows.append(f"{lab} & {pc(c['raw90'])} & {pc(c['conformal90'])} & {pc(oth['conf90'])} & {pc(s20['conf90'])} & "
                f"{pc(hz['1']['conf90'])} / {pc(hz['4']['conf90'])} & {pc(sz['small']['conf90'])} / {pc(sz['large']['conf90'])} & "
                f"{pc(c['below_q05'])} & {f2(c['mean_pit'])} \\\\")
table("calibration", [
    "\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrrrrrrr}", "\\toprule",
    " & \\multicolumn{2}{c}{90\\% coverage} & \\multicolumn{4}{c}{Conformal 90\\% coverage, by} & Below & Mean \\\\",
    "\\cmidrule(lr){2-3}\\cmidrule(lr){4-7}",
    " & Raw & Conformal & Other targets & 2020Q2--2021Q1 & $h$ = 1 / 4 & Small / large firms & 5\\% quantile & PIT \\\\",
    "\\midrule", *rows, "\\bottomrule", "\\end{tabular}}"])
cr, cc = CAL["revenue"], CAL["cash_like"]
m("CalRevRaw", pc(cr["raw90"]))
m("CalRevConf", pc(cr["conformal90"]))
m("CalCashRaw", pc(cc["raw90"]))
m("CalCashConf", pc(cc["conformal90"]))
m("CalRevStress", pc(cr["by"]["stress_2020"]["2020Q2-2021Q1 targets"]["conf90"]))
m("CalCashStress", pc(cc["by"]["stress_2020"]["2020Q2-2021Q1 targets"]["conf90"]))
m("CalRevBelow", pc(cr["below_q05"]))
m("CalCashBelow", pc(cc["below_q05"]))
m("CalCashWidthSizeT", f1(cc["width_regression"]["log_rev"]["t"]))
m("CalCashErrSizeT", f1(cc["error_regression"]["log_rev"]["t"]))
m("CalRevYearMin", pc(min(v["conf90"] for v in cr["by"]["year"].values())))

# ------------------------------------------------------------------ 8. data audit
if AUDIT.exists():
    A = json.loads(AUDIT.read_text(encoding="utf-8"))
    m("AudFirmQuarters", big(A["current"]["firm_quarters"]))
    m("AudLoaded", big(A["current"]["loaded"]))
    m("AudGapsOld", big(A["old_window_75_105"]["gaps"]))
    m("AudGapsNew", big(A["current"]["gaps"]))
    m("AudFirmsOld", A["old_window_75_105"]["companies_with_gaps"])
    m("AudFirmsNew", A["current"]["companies_with_gaps"])
    m("AudRecovered", A["companies_recovered"])
    m("AudLatest", pc(A["current"]["share_latest_matches_last_filing"]))
    m("AudNoFiling", big(A["current"].get("gaps_no_filing") or 0))
    m("AudUntagged", big(A["current"].get("gaps_filed_untagged") or 0))

# ------------------------------------------------------------------ 9. second round (docs/REVISION_PLAN_2.md)
P2 = R.get("plan2", {})
if P2:
    rs = P2["revised_spec"]["global"]
    m("RevTestN", big(rs["n"]))
    m("RevFirstYear", min(rs["chosen"]))
    m("RevMaeBase", f1(rs["median_ae_baseline"]))
    m("RevMaeNew", f1(rs["median_ae_revised"]))
    m("RevDiff", f1(-rs["diff"]["diff"]))
    m("RevDiffLo", f1(-rs["diff"]["ci"][1]))
    m("RevDiffHi", f1(-rs["diff"]["ci"][0]))
    m("RevAucBase", f3(rs["auc_bk_baseline"]))
    m("RevAucNew", f3(rs["auc_bk_revised"]))
    m("RevAccepted", "accepted" if rs["accepted"] else "rejected")
    m("RevNone", f1(P2["revised_spec"]["grid_median_ae"]["prior_none"]))
    m("RevFive", f1(P2["revised_spec"]["grid_median_ae"]["prior_share_05"]))
    ri = P2["revised_spec"]["industry"]
    m("RevIndMae", f1(ri["median_ae_revised"]))
    m("RevIndAuc", f3(ri["auc_bk_revised"]))
    ov = P2["overreaction"]
    m("ElastCfoTwin", f2(ov["cfo"]["twin"]))
    m("ElastCfoReal", f2(ov["cfo"]["real"]))
    m("ElastCfoRatio", f1(ov["cfo"]["ratio"]))
    m("ElastEbitdaRatio", f1(ov["ebitda"]["ratio"]))
    m("ElastCapexRatio", f2(ov["capex"]["ratio"]))
    ch = P2["cash_hybrid"]
    if ch.get("skill_hybrid_vs_rw") is not None:
        m("CashHybSkill", sp(ch["skill_hybrid_vs_rw"], 1))
        m("CashHybLo", sp(ch["skill_hybrid_ci"][0], 1))
        m("CashHybHi", sp(ch["skill_hybrid_ci"][1], 1))
        m("CashHybVerdict", "meets" if ch["accepted"] else "misses")
        m("CashLamLo", f2(min(ch["lambda"].values())))
        m("CashLamHi", f2(max(ch["lambda"].values())))
    cal2 = P2["calibration"]
    for var, tag in (("revenue", "Rev"), ("cash_like", "Cash")):
        c = cal2[var]
        m(f"CalCond{tag}", pc(c["coverage"]["cond"]))
        m(f"CalAci{tag}", pc(c["coverage"]["aci"]))
        stx = c["by"]["stress"]["2020Q2-2021Q1"]
        m(f"CalCond{tag}Stress", pc(stx["cond_hit"]))
        m(f"CalAci{tag}Stress", pc(stx["aci_hit"]))
        m(f"CalCond{tag}Ok", "meets" if c["accepted"]["cond"] else "misses")
        m(f"CalAci{tag}Ok", "meets" if c["accepted"]["aci"] else "misses")
    rows = []
    for var, lab in (("revenue", "Revenue"), ("cash_like", "Cash")):
        c = cal2[var]["by"]
        for gname, glab in (("stress", "Target quarters"), ("size", "Size tercile"), ("volatility", "Volatility tercile")):
            for k, v in c[gname].items():
                kk = {"0.0": "low", "1.0": "mid", "2.0": "high"}.get(k, k)
                rows.append(f"{lab} & {glab} & {kk} & {pc(v['cond_hit'])} & {pc(v['aci_hit'])} \\\\")
        rows.append("\\addlinespace")
    table("calibration2", ["\\begin{tabular}{lllrr}", "\\toprule",
                           "Variable & Split & Group & Group-conditional & Adaptive (ACI) \\\\", "\\midrule",
                           *rows[:-1], "\\bottomrule", "\\end{tabular}"])
    tm = P2["timing"]
    m("TimCashTwin", f2(tm["cash_half"]["twin"]))
    m("TimCashNoLoops", f2(tm["cash_half"]["no_loops"]))
    m("TimCashStatic", f2(tm["cash_half"]["static"]))
    m("TimCashDiff", f2(tm["cash_half"]["twin_minus_no_loops"]["diff"]))
    m("TimCashDiffLo", f2(tm["cash_half"]["twin_minus_no_loops"]["ci"][0]))
    m("TimCashDiffHi", f2(tm["cash_half"]["twin_minus_no_loops"]["ci"][1]))
    m("TimDebtTwin", f2(tm["debt_raise"]["twin"]))
    m("TimDebtNoLoops", f2(tm["debt_raise"]["no_loops"]))
    th = P2["thresholds"]
    rows = []
    for ev, lab in (("cash", "Cash falls below share of opening"), ("debt", "New borrowing above share of revenue"),
                    ("div", "Dividend cut by at least"), ("capex", "Capex cut by at least")):
        for x, v in th.get(ev, {}).items():
            rows.append(f"{lab} & {pc(float(x))} & {pc(v['rate'])} & {f2(v['auc_twin'])} & {f2(v['auc_no_loops'])} \\\\")
    table("thresholds", ["\\begin{tabular}{lrrrr}", "\\toprule",
                         "Event & Threshold & Rate & Twin AUC & No loops AUC \\\\", "\\midrule", *rows,
                         "\\bottomrule", "\\end{tabular}"])
    ep = P2["episodes"]
    rows = []
    for y, lab in (("2015", "2015--16 commodity bust (cutoff Feb 2015)"), ("2020", "2020 pandemic (Feb 2020)"),
                   ("2022", "2022 rate shock (Feb 2022)")):
        if y not in ep:
            continue
        e = ep[y]
        for o, olab in (("y_burn8", "raw"), ("y_abn_burn8", "abnormal")):
            t = e[o].get("t_robust") or e[o]["t"]
            rows.append(f"{lab if o == 'y_burn8' else ''} & {big(e['n']) if o == 'y_burn8' else ''} & "
                        f"{pc(e['median_depth']) if o == 'y_burn8' else ''} & {olab} & {f1(t['exp'])} & {f1(t['twin'])} & "
                        f"{f1(t['fcf'])} & {f1(t['formula']) if 'formula' in t else '--'} \\\\")
        rows.append("\\addlinespace")
    table("episodes", ["\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrlrrrr}", "\\toprule",
                       " & & Median & & \\multicolumn{4}{c}{Rank regression $t$, industry-clustered} \\\\",
                       "\\cmidrule(lr){5-8}",
                       "Episode & Firms & shock & Burn & Industry shock & Twin at shock & FCF margin & Formula \\\\",
                       "\\midrule",
                       *rows[:-1], "\\bottomrule", "\\end{tabular}}"])
    for y, tag in (("2015", "Fifteen"), ("2020", "Twenty"), ("2022", "TwentyTwo")):
        if y in ep:
            m(f"Epi{tag}T", f1(ep[y]["y_abn_burn8"]["t"]["twin"]))
            m(f"Epi{tag}TRobust", f1(ep[y]["y_abn_burn8"]["t_robust"]["twin"]))
            m(f"Epi{tag}FormulaT", f1(ep[y]["y_abn_burn8"]["t_robust"]["formula"]))
            m(f"Epi{tag}Clusters", ep[y]["y_abn_burn8"]["n_clusters"])
            m(f"Epi{tag}Depth", pc(ep[y]["median_depth"]))
    m("EpiVerdict", "generalizes" if ep.get("generalizes") else "does not generalize")
    fm = P2["fcf_mechanism"]
    m("FcfCapexShare", pc(fm["capex_share_of_fcf_gain"]))
    m("FcfGainFcf", f2(fm["fcf"]["gain"]))
    m("FcfGainCfo", f2(fm["cfo"]["gain"]))
    m("FcfGainCapex", f2(fm["capex"]["gain"]))
    sm_ = P2["small_firms"]
    m("SmallN", big(sm_["n"]))
    m("SmallFirms", big(sm_["n_firms"]))
    m("SmallAucTwin", f2(sm_["auc_bk_twin"]))
    m("SmallAucFormula", f2(sm_["auc_bk_formula"]))
    m("SmallBk", sm_["bk_events"])
    m("SmallMaeTwin", f1(sm_["median_ae"]["T1"]))
    m("SmallMaeSixteen", f1(sm_["median_ae"]["N3"]))
    m("SmallIncr", f2(sm_["incr_twin_vs_16q"]))
    tw = P2["two_way"]
    m("TwoWayLo", f2(tw["ci_two_way"][0]))
    m("TwoWayHi", f2(tw["ci_two_way"][1]))
    at = P2.get("attrition", {})
    if "with_outcome" in at:
        m("AttrShare", pc(at["share_with_outcome"]))
        m("AttrShareBk", pc(at["share_with_outcome_bankrupt"]))
        m("AttrShareNonBk", pc(at["share_with_outcome_not_bankrupt"]))
        m("AttrTwin", f1(at["median_ae_twin_cfo"]))
        m("AttrTwinIpw", f1(at["median_ae_twin_cfo_ipw"]))
        m("AttrSixteen", f1(at["median_ae_N3_cfo"]))
        m("AttrSixteenIpw", f1(at["median_ae_N3_cfo_ipw"]))
    v = P2["verdicts"]
    m("HOneVerdict", "accepted" if v["H1_accepted"] else "rejected")
    m("HThreeVerdict", "accepted" if v["H3_accepted"] else "rejected")
    m("HThreeWins", v["H3_auc_wins"])
    ex = P2.get("examples", {})
    if ex.get("share_right_sign") is not None:
        m("ExRightSign", pc(ex["share_right_sign"]))
        for label, tag in (("amazon_2020", "Amzn"), ("ge_2016", "Ge"), ("ford_2020", "Ford"), ("gm_2020", "Gm")):
            if label in ex:
                e = ex[label]
                m(f"Ex{tag}Rev", f"{e['rev_change']:.0f}\\%".replace("-", "$-$"))
                m(f"Ex{tag}Rule", f"{e['rule']:.0f}\\%")
                m(f"Ex{tag}Twin", f"{e['twin']:.0f}\\%".replace("-", "$-$"))
                m(f"Ex{tag}Real", f"{e['real']:.0f}\\%".replace("-", "$-$"))
    cc = P2.get("census", {})
    if "found" in cc:
        m("CensusFound", cc["found"])
        m("CensusLegacy", cc["legacy"])
        m("CensusRepeat", pc(cc["share_repeat"]))
        m("CensusMissing", " and ".join(cc["missing"]).replace("&", "\\&"))
    hl = P2["holm"]
    HN = {"decision_capex_cut": "Liquidity: capex cut, twin added", "decision_cash_half": "Liquidity: cash halves, twin added",
          "decision_debt_raise": "Liquidity: new borrowing, twin added", "decision_div_cut": "Liquidity: dividend cut, twin added",
          "panel_severe_burn": "Distress: severe burn, twin beyond formula",
          "panel_abnormal_burn": "Distress: abnormal burn, twin beyond formula",
          "panel_coverage_collapse": "Distress: coverage collapse, twin beyond formula",
          "panel_dividend_cut": "Distress: dividend cut, twin beyond formula",
          "panel_bankruptcy": "Distress: bankruptcy, twin beyond formula",
          "bankruptcy_all_twin_minus_formula": "Bankruptcy AUC: twin minus formula, all firms",
          "bankruptcy_weak_twin_minus_formula": "Bankruptcy AUC: twin minus formula, weak firms"}
    rows = []
    for k, adj in sorted(hl.items(), key=lambda kv: kv[1]):
        lab = HN.get(k, k.replace("hybrid_", "Combination: ").replace("_N3+T1_vs_", " twin vs. ").replace("N3+", "16q + ")
                     .replace("cfo", "OCF").replace("fcf", "FCF").replace("N1", "4q").replace("N5", "regression")
                     .replace("N6", "regression with timing"))
        rows.append(f"{lab} & {'$<$0.001' if adj < 0.001 else f'{adj:.3f}'} \\\\")
    table("holm", ["\\begin{tabular}{lr}", "\\toprule", "Secondary comparison & Holm-adjusted $p$ \\\\", "\\midrule",
                   *rows, "\\bottomrule", "\\end{tabular}"])

# ------------------------------------------------------------------ 10. global sensitivity to the assumptions
SOB = PAPER / "sobol_assumptions.json"
if SOB.exists():
    SB = json.loads(SOB.read_text(encoding="utf-8"))
    m("SobN", SB["n_firm_years"])
    m("SobPoints", SB["n_points"])
    m("SobMaeMin", f1(SB["median_ae"]["min"]))
    m("SobMaeMax", f1(SB["median_ae"]["max"]))
    m("SobIncrMin", f2(SB["incremental"]["min"]))
    m("SobIncrMax", f2(SB["incremental"]["max"]))
    top = max(SB["median_ae"]["indices"], key=lambda r: r["ST"])
    m("SobTopLabel", lower(top["label"]))
    m("SobTopST", f2(min(top["ST"], 1.0)))
    rest = sum(max(r["ST"], 0) for r in SB["median_ae"]["indices"] if r is not top)
    m("SobRestST", f2(rest))
    if SB.get("specified"):
        m("SobSpecMae", f1(SB["specified"]["median_ae"]))
        m("SobSpecIncr", f2(SB["specified"]["incremental"]))
    rows = []
    for a, b in zip(SB["median_ae"]["indices"], SB["incremental"]["indices"], strict=True):
        def cl(x, hi=1.0):
            return min(max(x, 0.0), hi)

        rows.append(f"{a['label']} & {a['range'][0]:g}--{a['range'][1]:g} & {f2(cl(a['S1'], cl(a['ST'])))} & "
                    f"{f2(cl(a['ST']))} {ci_txt([cl(c) for c in a['ST_ci']])} & {f2(cl(b['S1'], cl(b['ST'])))} & "
                    f"{f2(cl(b['ST']))} \\\\")
    table("sobol_assumptions", ["\\resizebox{\\linewidth}{!}{%", "\\begin{tabular}{lrrlrr}", "\\toprule",
                                " & & \\multicolumn{2}{c}{Median error} & \\multicolumn{2}{c}{Incremental $\\rho$} \\\\",
                                "\\cmidrule(lr){3-4}\\cmidrule(lr){5-6}",
                                "Assumption & Range & $S_1$ & $S_T$ [95\\% CI] & $S_1$ & $S_T$ \\\\", "\\midrule", *rows,
                                "\\bottomrule", "\\end{tabular}}"])

# ------------------------------------------------------------------ figures
by = cfo["by_year"]
years = sorted(int(y) for y in by)
fig, ax = plt.subplots(figsize=(7.0, 2.5))
w = 0.27
ax.bar(np.array(years) - w, [by[str(y)]["T1|N1"] for y in years], w, color=BLUE, label="Twin vs. 4-quarter margin")
ax.bar(np.array(years), [by[str(y)]["N3|N1"] for y in years], w, color="#b9b8ad",
       label="16-quarter margin vs. 4-quarter margin (a null)")
ax.bar(np.array(years) + w, [by[str(y)]["T1|N6"] for y in years], w, color="#1d4f91",
       label="Twin vs. cash-revenue regression")
ax.axhline(0, color=MUTED, lw=0.6)
ax.set_xticks(years)
ax.set_ylabel("Incremental $\\rho$")
ax.set_xlabel("Cutoff (15 February of); realized revenue of the next eight quarters given to every model")
ax.legend(fontsize=6.8, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))
fig.tight_layout()
fig.savefig(FIG / "structural.pdf")
plt.close(fig)

fig, ax = plt.subplots(figsize=(7.0, 2.2))
order = ["N1", "N2", "N3", "N4", "N5", "N6", "T0", "T1"]
yy = np.arange(len(order))[::-1]
ax.barh(yy, [cfo["levels"][k]["median_ae"] for k in order],
        color=[BLUE if k.startswith("T") else "#b9b8ad" for k in order], height=0.6)
for y_, k in zip(yy, order, strict=True):
    ax.text(cfo["levels"][k]["median_ae"] + 0.1, y_, f"{cfo['levels'][k]['median_ae']:.1f}", va="center", fontsize=7)
ax.set_yticks(yy, [MODEL[k].replace("$a + b\\cdot$", "a + b·") for k in order])
ax.set_xlabel("Median absolute error, cumulative operating cash flow over 8 quarters (pp of trailing revenue)")
ax.grid(axis="y", visible=False)
fig.tight_layout()
fig.savefig(FIG / "ladder.pdf")
plt.close(fig)

fig, ax = plt.subplots(figsize=(7.0, 2.2))
for var, col, lab in (("revenue", BLUE, "Revenue"), ("cash_like", ORANGE, "Cash")):
    yb = CAL[var]["by"]["year"]
    ks = sorted(yb, key=int)
    ax.plot([int(k) for k in ks], [yb[k]["conf90"] * 100 for k in ks], color=col, marker="o", ms=3, label=f"{lab}, conformal")
    ax.plot([int(k) for k in ks], [yb[k]["raw90"] * 100 for k in ks], color=col, ls=":", lw=1, label=f"{lab}, raw")
ax.axhline(90, color=MUTED, lw=0.6, ls="--")
ax.set_ylabel("Coverage of 90% intervals (%)")
ax.set_xlabel("Forecast origin (15 February of)")
ax.legend(fontsize=6.8, ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0))
fig.tight_layout()
fig.savefig(FIG / "calibration.pdf")
plt.close(fig)

# ------------------------------------------------------------------ the paper in one picture (README, site)
SURFACE, TEXT, TEXT2 = "#fcfcfb", "#1f1e1b", "#5c5b55"
with plt.rc_context({"font.family": "sans-serif", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                     "xtick.color": TEXT2, "ytick.color": TEXT2, "axes.labelcolor": TEXT2}):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.3), gridspec_kw={"width_ratios": [1, 1], "wspace": 0.55})
    fig.patch.set_facecolor(SURFACE)
    labels = {"N1": "Margin, 4 quarters", "N3": "Margin, 16 quarters", "N6": "Regression on revenue",
              "T1": "Twin alone", "N3+N5": "16q margin + share of regression's departure",
              "N3+T1": "16q margin + share of twin's departure"}
    ks = ["N1", "N3", "N6", "T1", "N3+N5", "N3+T1"]
    yv = np.arange(len(ks))[::-1]
    vals = [hy["mae_w"][k] for k in ks]
    a1.barh(yv, vals, 0.6, color=[ORANGE if k == "N3+T1" else BLUE if k == "T1" else "#b9b8ad" for k in ks])
    for y_, v in zip(yv, vals, strict=True):
        a1.text(v + 0.15, y_, f"{v:.1f}", va="center", fontsize=9, color=TEXT)
    a1.set_yticks(yv, [labels[k] for k in ks], color=TEXT)
    a1.set_xlabel("Out-of-sample error, 8-quarter operating cash flow (pp of revenue)")
    a1.grid(axis="y", visible=False)
    a1.set_facecolor(SURFACE)
    a1.set_title("1  Given the revenue that happened, how much cash?\nAlone the twin is the least accurate; blended into the\n"
                 "best rule it helps, but a simple regression helps almost as much", loc="left", fontsize=10.5, color=TEXT,
                 pad=10)
    pk = [("Twin (simulated)", BP["all"]["predictors"]["twin"]["auc"], BP["weak"]["predictors"]["twin"]["auc"]),
          ("Twin's formula, no simulation", BP["all"]["predictors"]["formula"]["auc"], BP["weak"]["predictors"]["formula"]["auc"]),
          ("Ohlson O-score", BP["all"]["predictors"]["ohlson_o"]["auc"], BP["weak"]["predictors"]["ohlson_o"]["auc"]),
          ("Altman Z''", BP["all"]["predictors"]["altman_z2"]["auc"], BP["weak"]["predictors"]["altman_z2"]["auc"])]
    yv = np.arange(len(pk))[::-1]
    for i, (_n, a_, b_) in enumerate(pk):
        a2.barh(yv[i] + 0.19, a_, 0.34, color=BLUE)
        a2.barh(yv[i] - 0.19, b_, 0.34, color=ORANGE)
        a2.text(a_ + 0.005, yv[i] + 0.19, f"{a_:.2f}", va="center", fontsize=8.5, color=TEXT)
        a2.text(b_ + 0.005, yv[i] - 0.19, f"{b_:.2f}", va="center", fontsize=8.5, color=TEXT)
    a2.set_yticks(yv, [p[0] for p in pk], color=TEXT)
    a2.set_xlim(0.5, 0.95)
    a2.set_xlabel(f"AUC, bankruptcy petition within 2 years ({BP['all']['events']} petitions, 2014-2024)")
    a2.grid(axis="y", visible=False)
    a2.set_facecolor(SURFACE)
    a2.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
              labels=["All filers", "Already-weak filers"], loc="upper left", fontsize=8.5, frameon=False, ncol=2,
              bbox_to_anchor=(-0.02, -0.16))
    a2.set_title("2  Who will fail?\nThe twin ranks defaults well, but no better than\nits own score without simulation",
                 loc="left", fontsize=10.5, color=TEXT, pad=10)
    for ax in (a1, a2):
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(ROOT / "docs" / "findings.png", dpi=170, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

# ------------------------------------------------------------------ summary for the dashboard's evidence page
summary = {
    "samples": {"universe": len(u) - 1, "firm_years": smp["panel_firm_years"], "firms": smp["panel_firms"],
                "transmission_firm_years": T["n"], "bankruptcies": BP["all"]["events"]},
    "ladder": [{"key": k, "label": MODEL[k].replace("$a + b\\cdot$", "a + b·"), "median_ae": cfo["levels"][k]["median_ae"]}
               for k in MODEL],
    "incremental": {"twin_vs_4q": inc["N1"]["T1"]["rho"], "16q_vs_4q": inc["N1"]["N3"]["rho"],
                    "twin_vs_16q": inc["N3"]["T1"]["rho"], "encompassing_t": cfo["encompassing"]["levels"]["t"]["T1"],
                    "encompassing_t_two_way": (cfo["encompassing"].get("all_two_way") or {}).get("t", {}).get("T1")},
    # which specification the numbers come from (the paper reports v2-pre, v2-rev and v3 side by side)
    "spec": {"spec": R.get("provenance", {}).get("spec"), "env_spec": R.get("provenance", {}).get("env", {}).get("FINTWIN_SPEC"),
             "selection": "walk-forward" if R.get("provenance", {}).get("env", {}).get("FINTWIN_SELECTION") else "defaults",
             "snapshot_digest": R.get("provenance", {}).get("snapshot_digest")},
    "combination": {var: {k: T[var]["hybrid"]["mae_w"][k] for k in ("N3", "N3+N5", "N3+T1")} for var in ("cfo", "fcf")},
    "bankruptcy": {sub: {k: BP[sub]["predictors"][k]["auc"] for k in ("twin", "formula", "ohlson_o", "altman_z2")}
                   for sub in ("all", "weak")} | {"weak_share": BP["weak"]["share_of_events"]},
}
(ROOT / "web" / "public" / "data" / "research_summary.json").write_text(json.dumps(summary), encoding="utf-8")

# ------------------------------------------------------------------ plain-text abstract (SSRN, Zenodo) from the LaTeX one
def plain_abstract() -> str:
    import re

    tex = (PAPER / "fintwin.tex").read_text(encoding="utf-8")
    start = tex.index("\\begin{abstract}") + len("\\begin{abstract}")
    body = tex[start: tex.index("\\end{abstract}", start)]
    body = body.split("\\medskip")[0]  # the second version kept the keywords inside the abstract
    body = body.replace("\\noindent", "").replace("\\twin{}", "FinTwin").replace("\\twin", "FinTwin")
    # the revision-3 macros (rev3_assets.py) are used in the abstract too
    every = dict(macros)
    rev3 = PAPER / "rev3_numbers.tex"
    if rev3.exists():
        every |= dict(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}\s*$", rev3.read_text(encoding="utf-8"), re.M))
    body = re.sub(r"\\([A-Za-z]+)\{\}", lambda mm: every.get(mm.group(1), mm.group(0)), body)
    body = re.sub(r"\\([A-Za-z]+)", lambda mm: every.get(mm.group(1), mm.group(0)), body)
    for a_, b_ in (("$-$", "-"), ("\\%", "%"), ("{,}", ","), ("---", " - "), ("--", "-"), ("$", ""), ("\\&", "&"),
                   ("~", " "), ("``", '"'), ("''", '"')):
        body = body.replace(a_, b_)
    return " ".join(body.split())


(PAPER / "abstract.txt").write_text(plain_abstract() + "\n", encoding="utf-8")

(PAPER / "research_numbers.tex").write_text(
    "% generated by engine/scripts/research_assets.py from research.json\n"
    + "\n".join(f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(macros.items())) + "\n",
    encoding="utf-8",
)
print(f"{len(macros)} macros, {len(list(TAB.glob('*.tex')))} tables -> {PAPER}")
