"""Numbers and the summary table of REVISION_PLAN_4 (docs/paper/rev4/plan4.json; P4-1 from plan4_p41.json, the
addendum-2 rerun, when present) -> docs/paper/rev4_numbers.tex and docs/paper/tables/rev4_tests.tex."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

PAPER = Path(__file__).resolve().parents[2] / "docs" / "paper"
R = json.loads((PAPER / "rev4" / "plan4.json").read_text(encoding="utf-8"))
P41 = PAPER / "rev4" / "plan4_p41.json"
if P41.exists():
    R["P4-1"] = json.loads(P41.read_text(encoding="utf-8"))["P4-1"]
macros: dict[str, str] = {}


def m(name: str, value) -> None:
    assert name.isalpha() and name not in macros, name
    macros[name] = str(value)


def ok(x) -> bool:
    return x is not None and np.isfinite(x)


def fx(x, d=2):
    return f"{x:.{d}f}".replace("-", "$-$") if ok(x) else "--"


def pc(x, d=0):
    return f"{100 * x:.{d}f}\\%" if ok(x) else "--"


def pv(p):
    if not ok(p):
        return "--"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def prel(p):
    """p with its relation, for use after a math-mode p: '$<$0.001' or '$=$0.023'."""
    return pv(p) if ok(p) and p < 0.001 else "$=$" + pv(p)


def big(n):
    return f"{int(n):,}".replace(",", "{,}")


# ------------------------------------------------------------------ reproduction
rep = R["reproduction"]
m("PRepN", big(rep["n"]))
m("PRepShare", pc(rep["share_equal"]))

# ------------------------------------------------------------------ P4-1 unconditional
a = R["P4-1"]
lv = a["levels"]
m("PUncN", big(a["n"]))
for k, tag in (("T1u", "Twin"), ("R1u", "Rw"), ("R2u", "Own"), ("R3u", "Four")):
    m(f"PUncMed{tag}", fx(lv[k]["median_ae"]))
    m(f"PUncMean{tag}", fx(lv[k]["mean_ae"], 1))
A = a["test_A"]
m("PUncStat", fx(A["statistic"]))
m("PUncLo", fx(A["decision"]["ci"][0]))
m("PUncHi", fx(A["decision"]["ci"][1]))
m("PUncG", A["decision"]["G"])
m("PUncWorse", A["decision"]["G"] - A["decision"]["years_negative"])
m("PUncDmP", pv(A["dm_abs"]["p"]))
m("PUncWildP", pv(A["wild_p_dm"]))
m("PUncRandP", pv(A["randomization_p"]))
m("PUncVerdict", "succeeds" if A["success"] else "fails")
B = a["test_B"]
m("PUncCrpsTwin", fx(B["crps_twin"], 1))
m("PUncCrpsRival", fx(B["crps_rival"], 1))
m("PUncCrpsP", pv(B["p_one_sided"]))
m("PUncCovTwin", pc(B["coverage90_twin"]))
m("PUncCovRival", pc(B["coverage90_rival"]))
m("PUncDenYears", B["years"])
m("PUncDenBetter", B["years_twin_better"])
m("PUncDenVerdict", "succeeds" if B["success"] else "fails")
c = a["combination"]
m("PUncGainW", pc(c["gain_winsorized_mae"], 1))
m("PUncGainMed", pc(c["gain_median_ae"], 1))
m("PUncGainRaw", pc(c["gain_raw_mae"], 1))
ws = list(c["w"].values())
m("PUncWMin", fx(min(ws)))
m("PUncWMax", fx(max(ws)))

# ------------------------------------------------------------------ P4-2 second model
b = R["P4-2"]
t = b["test"]
m("PMlMed", fx(t["median_a"]))
m("PMlMedNthree", fx(t["median_b"]))
m("PMlLo", fx(t["decision"]["ci"][0]))
m("PMlHi", fx(t["decision"]["ci"][1]))
m("PMlG", t["decision"]["G"])
m("PMlBetter", t["decision"]["years_negative"])
m("PMlVerdict", "succeeds" if t["success"] else "fails")
m("PMlMean", fx(t["mean_a"], 1))
m("PMlMeanNthree", fx(t["mean_b"], 1))
m("PMlDmP", pv(t["dm_abs"]["p"]))
v = b["vs_T1"]
m("PMlTwinLo", fx(v["decision"]["ci"][0]))
m("PMlTwinHi", fx(v["decision"]["ci"][1]))
m("PMlTwinMed", fx(v["median_b"]))
m("PMlLevN", big(b["levels_n"]))
m("PMlLevTwinMean", fx(b["levels"]["T1"]["mean_ae"], 0))
e = b["encompassing_levels"]
tt = dict(zip(e["names"], e["t"], strict=True))
m("PMlEncTwinT", fx(tt["T1"], 1))
m("PMlEncMlT", fx(tt["ML1"], 1))
m("PMlEncNthreeT", fx(tt["N3"], 1))
m("PMlEncCrit", fx(e["t_crit"]))
cm = b["combination_N3_ML1"]
m("PMlCombGainW", pc(cm["gain_winsorized_mae"], 1))
m("PMlCombGainMed", pc(cm["gain_median_ae"], 1))
de = b["density"]
m("PMlCrps", fx(de["crps_ml1"], 1))
m("PMlCrpsEmp", fx(de["crps_empirical"], 1))
m("PMlCrpsP", pv(de["dm_ml1_vs_empirical"]["p"]))
m("PMlCov", pc(de["coverage90_ml1"]))

# ------------------------------------------------------------------ P4-3 MCS
c3 = R["P4-3"]
raw = c3["raw_mean_19"]
m("PMcsRawSize", len(raw["included"]))
m("PMcsRawTwinP", pv(raw["p_mcs"]["T1"]))
for key, tag in (("with_ml1_train_median", "Med"), ("with_ml1_train_mean", "Mean")):
    x = c3[key]
    m(f"PMcsMl{tag}Size", len(x["included"]))
    m(f"PMcsMl{tag}TwinP", pv(x["p_mcs"]["T1"]))
    m(f"PMcsMl{tag}TwinPrel", prel(x["p_mcs"]["T1"]))
    m(f"PMcsMl{tag}MlP", pv(x["p_mcs"]["ML1"]))
    m(f"PMcsMl{tag}NthreeP", pv(x["p_mcs"]["N3"]))

# ------------------------------------------------------------------ P4-4 inference by year
w4 = R["P4-4"]
m("PWildSoneP", pv(w4["S1"]["wild_p"]))
m("PRandSoneP", pv(w4["S1"]["randomization_p"]))
m("PWildEncP", pv(w4["encompassing_T1"]["p_wild"]))
m("PWildEncT", fx(w4["encompassing_T1"]["t_year_cluster"], 1))
m("PWildGainP", pv(w4["gain_N3T1_vs_N3"]["wild_p"]))

# ------------------------------------------------------------------ P4-5 scale-free
s5 = R["P4-5"]
rt = s5["relative"]["T1"]
m("PGmraeTwin", fx(rt["gmrae"]))
m("PGmraeTwinLo", fx(rt["gmrae_ci"][0]))
m("PGmraeTwinHi", fx(rt["gmrae_ci"][1]))
m("PGmraeTwinBeats", pc(rt["share_beats_N3"]))
m("PGmraeFour", fx(s5["relative"]["N1"]["gmrae"]))
m("PGmraeNoloops", fx(s5["relative"]["T0"]["gmrae"]))
m("PNearZeroN", s5["near_zero_excluded"])
m("PNearZeroTwin", fx(s5["without_near_zero"]["T1"]["median_ae"]))
m("PNearZeroNthree", fx(s5["without_near_zero"]["N3"]["median_ae"]))
m("PNearZeroTwinMean", fx(s5["without_near_zero"]["T1"]["mean_ae"], 0))

# ------------------------------------------------------------------ P4-6 density rivals
d6 = R["P4-6"]
m("PDenN", big(d6["n"]))
for k, tag in (("T1", "Twin"), ("H", "Het"), ("Q", "Qr")):
    m(f"PDenCrps{tag}", fx(d6["crps"][k], 1))
    m(f"PDenCov{tag}", pc(d6["coverage90"][k]))
m("PDenHetP", pv(d6["dm_T1_vs_H"]["p"]))
m("PDenQrP", pv(d6["dm_T1_vs_Q"]["p"]))
m("PDenCovVtwopre", pc(d6["spec_v2-pre"]["coverage90"]))
m("PDenCovVtworev", pc(d6["spec_v2-rev"]["coverage90"]))

# ------------------------------------------------------------------ P4-7 shortfall
s7 = R["P4-7"]
for key, tag in (("L2_recession", "Ltwo"), ("L1_recession", "Lone")):
    x = s7[key]
    m(f"PShort{tag}N", big(x["n"]))
    m(f"PShort{tag}Ev", big(x["events"]))
    m(f"PShort{tag}Raw", fx(x["bss_raw_vs_logit"]))
    m(f"PShort{tag}Recal", fx(x["bss_recal_vs_logit"], 3))
    m(f"PShort{tag}Lo", fx(x["recal_firm_block"]["ci"][0], 3))
    m(f"PShort{tag}Hi", fx(x["recal_firm_block"]["ci"][1], 3))
    m(f"PShort{tag}Res", fx(x["recalibrated"]["murphy"]["resolution"], 4))
    m(f"PShort{tag}ResLogit", fx(x["logit"]["murphy"]["resolution"], 4))
m("PShortVerdict", "succeeds" if s7["confirmatory"]["success"] else "fails")

# ------------------------------------------------------------------ P4-8 NBER
n8 = R["P4-8"]
m("PNberN", big(n8["n"]))
m("PNberDiffer", pc(n8["share_regime_differs"]))
m("PNberMed", fx(n8["median_ae"]["realtime"]))
m("PNberMedPlan", fx(n8["median_ae"]["plan3"]))
m("PNberShort", fx(n8["mean_short8_rec"]["realtime"], 3))
m("PNberShortPlan", fx(n8["mean_short8_rec"]["plan3"], 3))

# ------------------------------------------------------------------ P4-9 elasticity
e9 = R["P4-9"]
for key, tag in (("v3-wf", "Vthree"), ("v3", "Vthreedef"), ("v2-pre", "Vtwopre")):
    m(f"PEl{tag}", fx(e9[key]["ratio"]))
    m(f"PEl{tag}FirmLo", fx(e9[key]["ci_firm"][0]))
    m(f"PEl{tag}FirmHi", fx(e9[key]["ci_firm"][1]))
    m(f"PEl{tag}YearLo", fx(e9[key]["ci_year"][0]))
    m(f"PEl{tag}YearHi", fx(e9[key]["ci_year"][1]))

# ------------------------------------------------------------------ summary table
rows = [
    (
        "P4-1 A",
        "Unconditional point: simulator vs margin $\\times$ seasonal random walk",
        f"{fx(A['statistic'])} [{fx(A['decision']['ci'][0])}, {fx(A['decision']['ci'][1])}]",
        "fails" if not A["success"] else "succeeds",
    ),
    (
        "P4-1 B",
        "Unconditional density: CRPS simulator vs empirical rival",
        f"{fx(B['crps_twin'], 1)} vs {fx(B['crps_rival'], 1)} ($p$ {pv(B['p_one_sided'])})",
        "fails" if not B["success"] else "succeeds",
    ),
    (
        "P4-2",
        "Second model (pooled LAD) vs 16-quarter margin, median error",
        f"{fx(t['statistic'])} [{fx(t['decision']['ci'][0])}, {fx(t['decision']['ci'][1])}]",
        "fails" if not t["success"] else "succeeds",
    ),
    (
        "P4-7",
        "Recalibrated shortfall probability vs logit, label L2, BSS",
        f"{fx(s7['L2_recession']['bss_recal_vs_logit'], 3)} [{fx(s7['L2_recession']['recal_firm_block']['ci'][0], 3)}, {fx(s7['L2_recession']['recal_firm_block']['ci'][1], 3)}]",
        "fails" if not s7["confirmatory"]["success"] else "succeeds",
    ),
]
lines = [
    r"\begin{tabular}{llll}",
    r"\toprule",
    r"Test & Comparison & Statistic [95\% CI] & Verdict \\",
    r"\midrule",
    *[f"{a_} & {b_} & {c_} & {d_} \\\\" for a_, b_, c_, d_ in rows],
    r"\bottomrule",
    r"\end{tabular}",
]
(PAPER / "tables" / "rev4_tests.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
out = [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
(PAPER / "rev4_numbers.tex").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"rev4_numbers.tex: {len(macros)} macros; table rev4_tests")
