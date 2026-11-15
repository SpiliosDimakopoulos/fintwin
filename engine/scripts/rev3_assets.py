"""Macros and tables of the revision-3 evaluation (two pillars), from docs/paper/research.json and docs/paper/rev3/inputs.json.

    uv run python scripts/rev3_assets.py

Writes docs/paper/rev3_numbers.tex and docs/paper/tables/rev3_*.tex. Like research_assets.py, nothing is typed by hand.
Pillar A: point transmission (confirmatory v3 vs v2-pre, the family of 16, MCS, SPA, encompassing under absolute loss).
Pillar B: distribution and stress (B1 density, B2 liquidity shortfall, B3 credit events).
"""

import json
from math import comb
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "docs" / "paper"
TAB = PAPER / "tables"
R = json.loads((PAPER / "research.json").read_text(encoding="utf-8"))
X = json.loads((PAPER / "rev3" / "inputs.json").read_text(encoding="utf-8"))
macros: dict[str, str] = {}


def m(name: str, value) -> None:
    assert name.isalpha() and name not in macros, name
    macros[name] = str(value)


def ok(x) -> bool:
    return x is not None and np.isfinite(x)


def fx(x, d=2):
    return f"{x:.{d}f}".replace("-", "$-$") if ok(x) else "--"


def pct(x, d=1):
    return f"{100 * x:.{d}f}\\%".replace("-", "$-$") if ok(x) else "--"


def pv(p):
    if not ok(p):
        return "--"
    return "$<$0.001" if p < 0.001 else f"{p:.3f}"


def big(n):
    return f"{int(n):,}".replace(",", "{,}")


def ci(c, d=2):
    return f"[{fx(c[0], d)}, {fx(c[1], d)}]" if c else "--"


def table(name, lines):
    (TAB / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ S1: the confirmatory v3 vs v2-pre test
S1 = X["cross_spec"]["v3-wf_vs_v2-pre"]
m("SOneMedVthree", fx(S1["median_own"]["v3-wf"]))
m("SOneMedVtwo", fx(S1["median_own"]["v2-pre"]))
m("SOneStat", fx(S1["statistic"]))
m("SOneN", big(S1["n_common"]))
m("SOneContN", big(S1["continuity"]["n"]))
m("SOneContYears", f"{S1['continuity']['years'][0]}--{S1['continuity']['years'][1]}")
m("SOneLostThree", big(S1["lost"]["v3-wf"]))
m("SOneLostTwo", big(S1["lost"]["v2-pre"]))
m("SOneMean", fx(S1["decision"]["mean"]))
m("SOneLo", fx(S1["decision"]["ci"][0]))
m("SOneHi", fx(S1["decision"]["ci"][1]))
m("SOneG", S1["decision"]["G"])
m("SOneNeg", S1["years_negative"])
m("SOneBlockLo", fx(S1["year_block"]["ci"][0]))
m("SOneBlockHi", fx(S1["year_block"]["ci"][1]))
m("SOneContStat", fx(S1["continuity"]["statistic"]))
m("SOneDmMean", fx(S1["dm"]["mean"], 1))
m("SOneDmP", fx(S1["dm"]["p"]))
m("SOneVerdict", "succeeds" if S1["success"] else "fails")
m("SOneLost", S1["lost"]["v2-pre"] + S1["lost"]["v3-wf"])
S1f = X["cross_spec"].get("v3-wf_family_vs_v2-pre_family")
if S1f:
    m("SOneFamStat", fx(S1f["statistic"]))
    m("SOneFamVerdict", "succeeds" if S1f["success"] else "fails")
S1d = X["cross_spec"]["v3_vs_v2-pre"]
m("SOneDefStat", fx(S1d["statistic"]))

# ------------------------------------------------------------------ the specifications side by side
SPEC = [("v2-pre", "v2-pre (prior 35\\%)"), ("v2-rev", "v2-rev (prior 5\\%)"), ("v3", "v3, default $\\tau$, $\\lambda$"),
        ("v3-wf", "v3, walk-forward $\\tau$, $\\lambda$")]
sp = X["specs"]
for key, tag in (("v2-pre", "Vtwopre"), ("v2-rev", "Vtworev"), ("v3", "Vthreedef"), ("v3-wf", "Vthree")):
    s = sp[key]
    m(f"Mae{tag}", fx(s["mae"]["T1"], 1))
    m(f"Elast{tag}", fx(s["elasticity_ratio"]))
    m(f"Crps{tag}", fx(s["crps"]["twin"], 0))
lines = [r"\begin{tabular}{lrrrrrrr}", r"\toprule",
         r" & \multicolumn{2}{c}{Median abs.\ error} & Elasticity & Incr.\ $\rho$ & Enc.\ $t$ & Bankr. & Mean CRPS \\",
         r"\cmidrule(lr){2-3}", r"Specification & Simulator & 16q margin & ratio & vs 16q & (firm$\times$year) & AUC & (simulator) \\",
         r"\midrule"]
for key, label in SPEC:
    s = sp[key]
    lines.append(f"{label} & {fx(s['mae']['T1'], 1)} & {fx(s['mae']['N3'], 1)} & {fx(s['elasticity_ratio'])} & "
                 f"{fx(s['incr_T1_vs_N3'])} & {fx(s['enc_t_two_way'], 1)} & {fx(s['bk_auc_twin'])} & {fx(s['crps']['twin'], 0)} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_specs", lines)
m("SpecN", big(sp["v3-wf"]["n"]))

# ------------------------------------------------------------------ the ladder (descriptive, fixed 1,000-firm sample)
LAD = [("v2-pre-legacydata", "v2-pre, legacy data layer"), ("v2-pre", "v2-pre"), ("v2-pre+F5", "+ F5 (consistent CFO residual and tax)"),
       ("v2-pre+F5+F4", "+ F4 (missing D\\&A)"), ("v2-pre+F5+F4+F1", "+ F1 (posterior cost prior, default $\\tau$)"),
       ("v2-pre+F5+F4+F1+F2", "+ F2 (annual operating leverage)"), ("v3", "+ F3 and the rest = v3 (defaults)"),
       ("v3-wf", "v3, walk-forward $\\tau$ and $\\lambda$")]
lad = X["ladder"]
lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
         r"Rung & Firm-years & Simulator median abs.\ error & 16q margin & Elasticity ratio \\", r"\midrule"]
for key, label in LAD:
    if key in lad:
        s = lad[key]
        lines.append(f"{label} & {big(s['n'])} & {fx(s['mae']['T1'])} & {fx(s['mae']['N3'])} & {fx(s['elasticity_ratio'])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_ladder", lines)
m("LadN", big(lad["v2-pre"]["n"]))
m("LadPre", fx(lad["v2-pre"]["mae"]["T1"], 1))
m("LadFive", fx(lad["v2-pre+F5"]["mae"]["T1"], 1))
m("LadOne", fx(lad["v2-pre+F5+F4+F1"]["mae"]["T1"], 1))
m("LadThree", fx(lad["v3"]["mae"]["T1"], 1))
m("LadLegacy", fx(lad["v2-pre-legacydata"]["mae"]["T1"], 1))
m("LadLegacyN", big(lad["v2-pre-legacydata"]["n"]))

# ------------------------------------------------------------------ pillar A: family of 16, SPA, MCS
inf = R["transmission"]["panel"]["inference"]
fam = inf["family"]
NAME = {"T1": "Simulator", "N3+T1": "16q + simulator", "N3+N1": "16q + 4q", "N3+N5": "16q + regression"}
lines = [r"\begin{tabular}{llrrrrr}", r"\toprule",
         r"Outcome, loss & Forecast & $\Delta$ vs 16q & 95\% CI & $p$ & Romano--Wolf & Holm \\", r"\midrule"]
for k, v in fam.items():
    var, loss, rest = k.split("_", 2)
    model = rest.removesuffix("_vs_N3")
    lines.append(f"{var.upper()}, {loss} & {NAME[model]} & {fx(v['diff'])} & {ci(v['ci'])} & {pv(v['p'])} & "
                 f"{pv(v['p_romano_wolf'])} & {pv(v['p_holm'])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_family", lines)
m("FamB", big(inf["B"]))
m("FamRejects", sum(1 for v in fam.values() if v["p_romano_wolf"] < 0.05))
m("FamCombRejects", sum(1 for k, v in fam.items() if "N3+T1" in k and v["p_romano_wolf"] < 0.05))
m("FamTwinMedDiff", fx(fam["cfo_median_T1_vs_N3"]["diff"]))
m("FamTwinMedRw", pv(fam["cfo_median_T1_vs_N3"]["p_romano_wolf"]))
m("FamCombMedDiff", fx(fam["cfo_median_N3+T1_vs_N3"]["diff"]))
m("FamCombMedRw", pv(fam["cfo_median_N3+T1_vs_N3"]["p_romano_wolf"]))
m("FamCombMeanDiff", fx(fam["cfo_mean_N3+T1_vs_N3"]["diff"]))
m("FamCombMeanRw", pv(fam["cfo_mean_N3+T1_vs_N3"]["p_romano_wolf"]))
m("FamRegMeanRw", pv(fam["cfo_mean_N3+N5_vs_N3"]["p_romano_wolf"]))
spa = inf["spa"]
m("SpaCfoMed", pv(spa["cfo_median_family"]["p_consistent"]))
m("SpaCfoMean", pv(spa["cfo_mean_family"]["p_consistent"]))
m("SpaFcfMed", pv(spa["fcf_median_family"]["p_consistent"]))
m("SpaFcfMean", pv(spa["fcf_mean_family"]["p_consistent"]))
mcs = inf["mcs"]
m("McsSize", len(mcs["cfo_median"]["included"]))
m("McsTwinIn", "includes" if "T1" in mcs["cfo_median"]["included"] else "excludes")
m("McsTwinP", pv(mcs["cfo_median"]["p_mcs"]["T1"]))
m("McsCombP", pv(mcs["cfo_median"]["p_mcs"]["N3+T1"]))
g = inf["gains"]["cfo"]["N3+T1_vs_N3"]
m("GainPct", pct(g["gain_pct"]))
m("GainLo", pct(g["gain_pct_ci_year_block"][0]))
m("GainHi", pct(g["gain_pct_ci_year_block"][1]))
m("GainPos", g["positive_years"])
m("GainYears", g["n_years"])
m("GainDmP", pv(g["dm_abs"]["p"]))
m("GainDmPrel", pv(g["dm_abs"]["p"]) if g["dm_abs"]["p"] < 0.001 else "$=$" + pv(g["dm_abs"]["p"]))
gb = inf["gains"]["cfo"]["N3+T1_vs_N3+N1"]
m("GainFourPct", pct(gb["gain_pct"]))
m("GainFourLo", pct(gb["gain_pct_ci_year_block"][0]))
m("GainFourHi", pct(gb["gain_pct_ci_year_block"][1]))
m("GainFourPos", gb["positive_years"])
gr = inf["gains"]["cfo"]["N3+T1_vs_N3+N5"]
m("GainRegPct", pct(gr["gain_pct"]))
m("GainRegLo", pct(gr["gain_pct_ci_year_block"][0]))
m("GainRegHi", pct(gr["gain_pct_ci_year_block"][1]))
gl = inf["gains"]["cfo"]["N3+T1_vs_N3+T0"]
m("GainLoopsPct", pct(gl["gain_pct"], 2))
gf = inf["gains"]["fcf"]["N3+T1_vs_N3"]
m("GainFcfPct", pct(gf["gain_pct"]))
m("LamMin", fx(min(inf["lambda_cfo"]["N3+T1"].values())))
m("LamMax", fx(max(inf["lambda_cfo"]["N3+T1"].values())))

enc = R["transmission"]["panel"]["cfo"]["encompassing"]
m("EncTGOne", fx(enc["all_two_way_tG1"]["t"]["T1"], 1))
m("EncTGOneCrit", fx(enc["all_two_way_tG1"]["t_crit"]))
m("EncTGOnePsd", "positive semi-definite" if enc["all_two_way_tG1"]["psd"] else "not positive semi-definite")
m("EncAbsSixteen", fx(enc["abs_loss_encompassing"]["N3_encompasses_T1"]["t"]))
m("EncAbsSixteenP", pv(enc["abs_loss_encompassing"]["N3_encompasses_T1"]["p_one_sided"]))
m("EncAbsReg", fx(enc["abs_loss_encompassing"]["N6_encompasses_T1"]["t"]))
m("EncLadCoef", fx(enc["lad_levels"]["coef"]["T1"], 3))
m("EncLadT", fx(enc["lad_levels"]["t"]["T1"]))
m("EncLadRegT", fx(enc["lad_levels"]["t"]["N6"]))
m("DmAbsT", fx(enc["dm_abs"]["T1_vs_N3"]["t"]))
m("DmAbsP", pv(enc["dm_abs"]["T1_vs_N3"]["p"]))
ov = R["plan2"]["overreaction"]["cfo"]
m("ElastRatioExact", fx(ov["ratio"]))
m("ElastVerdict", "inside" if 0.8 <= ov["ratio"] <= 1.25 else "outside")

# ------------------------------------------------------------------ pillar B1: density
D = R["density"]
lines = [r"\begin{tabular}{llrrrrrr}", r"\toprule",
         r"Outcome & Benchmark & Mean CRPS & Mean CRPS & DM $t$ & $p$ & Years sim. & Verdict \\",
         r" & & (simulator) & (benchmark) & (firm$\times$year) & & better & \\", r"\midrule"]
for var in ("cfo", "fcf"):
    for b, lab in (("gaussian", "Gaussian"), ("empirical", "Empirical")):
        v = D[var][f"vs_{b}"]
        lines.append(f"{var.upper()} & {lab} & {fx(D[var]['crps']['twin'], 1)} & {fx(D[var]['crps'][b], 1)} & {fx(v['dm']['t'])} & "
                     f"{pv(v['dm']['p'])} & {v['years_twin_better']}/{len(D[var]['test_years'])} & "
                     f"{'success' if v['success'] else 'failure'} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_density", lines)
dc = D["cfo"]
m("DenN", big(dc["n"]))
m("DenCov", pct(dc["coverage90_twin"], 0))
m("DenCovFcf", pct(D["fcf"]["coverage90_twin"], 0))
sh = dc["pit"]["twin"]["shares"]
m("DenPitTails", pct(sh[0] + sh[-1], 0))
m("DenPitLow", pct(sh[0], 0))
m("DenPitHigh", pct(sh[-1], 0))
se = dc["pit"]["empirical"]["shares"]
m("DenPitEmpTails", pct(se[0] + se[-1], 0))
m("DenCrpsTwin", fx(dc["crps"]["twin"], 0))
m("DenCrpsGauss", fx(dc["crps"]["gaussian"], 0))
m("DenCrpsEmp", fx(dc["crps"]["empirical"], 0))
yr = dc["vs_gaussian"]["by_year_mean_diff"]
worst = max(yr, key=lambda y: yr[y])
m("DenWorstYear", worst)
m("DenWorstDiff", fx(yr[worst], 0))
m("DenBetterGauss", dc["vs_gaussian"]["years_twin_better"])
m("DenBetterEmp", dc["vs_empirical"]["years_twin_better"])
m("DenYears", len(dc["test_years"]))

# ------------------------------------------------------------------ pillar B2: liquidity shortfall
L = R["liquidity"]
lines = [r"\begin{tabular}{lllrrrrrrrr}", r"\toprule",
         r"Label & Horizon & Scenario & Firm-years & Events & \multicolumn{3}{c}{Brier score} & BSS vs & Log score & Sim. \\",
         r"\cmidrule(lr){6-8}", r" & & & & & Sim. & Logit & Z$''$ & logit & sim./logit & rel./res. \\", r"\midrule"]
SCN = {"realized_shock": "industry shock", "recession": "Recession"}
LBL = {"shortfall": "Shortfall", "credit_event": "Credit event"}
for lab in ("shortfall", "credit_event"):
    for k in ("4", "8"):
        for sc in ("realized_shock", "recession"):
            v = L[lab][k][sc]
            t, lg, z = v["twin"], v["logit"], v["altman_z2"]
            bss = 1 - t["brier"] / lg["brier"]
            mu = t["murphy"]
            lines.append(f"{LBL[lab]} & {k}q & {SCN[sc]} & {big(t['n'])} & {big(t['events'])} & {fx(t['brier'], 3)} & "
                         f"{fx(lg['brier'], 3)} & {fx(z['brier'], 3)} & {fx(bss)} & {fx(t['log'])}/{fx(lg['log'])} & "
                         f"{fx(mu['reliability'], 3)}/{fx(mu['resolution'], 3)} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_shortfall", lines)
P = L["primary"]
c8 = L["shortfall"]["8"]["recession"]
m("ShortN", big(c8["twin"]["n"]))
m("ShortEv", big(c8["twin"]["events"]))
m("ShortBase", pct(c8["twin"]["base_rate"]))
m("ShortMeanP", pct(c8["twin"]["mean_p"]))
m("ShortBrierTwin", fx(c8["twin"]["brier"], 3))
m("ShortBrierLogit", fx(c8["logit"]["brier"], 3))
m("ShortBss", fx(1 - c8["twin"]["brier"] / c8["logit"]["brier"]))
m("ShortBssLo", fx(P["year_block_ci"][0]))
m("ShortBssHi", fx(P["year_block_ci"][1]))
m("ShortVerdict", "succeeds" if P["success"] else "fails")
m("ShortRel", fx(c8["twin"]["murphy"]["reliability"], 3))
m("ShortRes", fx(c8["twin"]["murphy"]["resolution"], 3))
m("ShortResLogit", fx(c8["logit"]["murphy"]["resolution"], 3) if "murphy" in c8["logit"] else "--")
cur = c8["twin"]["murphy"]["curve"]
m("ShortLowBinShare", pct(cur[0]["n"] / c8["twin"]["n"], 0))
m("ShortLowBinRate", pct(cur[0]["y_mean"]))
m("ShortExcluded", L["in_bankruptcy_excluded"])

# ------------------------------------------------------------------ pillar B3: credit events (secondary)
C = R["credit_events"]
LAB = {"ce8": "Credit event (1.03, 2.04, 3.01), 8q", "ce4": "Credit event, 4q", "bk8": "Bankruptcy petition (1.03), 8q",
       "acc8": "Acceleration (2.04), 8q", "delist8": "Delisting notice (3.01), 8q"}
lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r"Event & Firm-years & Events & Simulator health [95\% CI] & Breach prob. & Recession breach prob. & Altman Z$''$ \\", r"\midrule"]
for k in ("bk8", "ce8", "ce4", "acc8", "delist8"):
    v = C[k]
    cell = lambda s, v=v: f"{fx(v[s]['auc'])} [{fx(v[s]['ci'][0])}, {fx(v[s]['ci'][1])}]"  # noqa: E731
    lines.append(f"{LAB[k]} & {big(v['n'])} & {big(v['events'])} & {cell('twin')} & {fx(v['pb_base']['auc'])} & "
                 f"{fx(v['recession8']['auc'])} & {fx(v['altman_z2']['auc'])} \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_credit", lines)
m("CeAucTwin", fx(C["ce8"]["twin"]["auc"]))
m("CeAucZ", fx(C["ce8"]["altman_z2"]["auc"]))
m("CeEv", big(C["ce8"]["events"]))
m("BkAucTwin", fx(C["bk8"]["twin"]["auc"]))
m("BkAucZ", fx(C["bk8"]["altman_z2"]["auc"]))

# ------------------------------------------------------------------ exploratory: non-accounting rivals (declared after the pre-spec)
E = R["exploratory_rivals"]
m("RivAucNonacc", fx(E["auc"]["nonacc"]))
m("RivAucBench", fx(E["auc"]["benchmarks"]))
m("RivAucTwin", fx(E["auc"]["twin_only"]))
m("RivAucAll", fx(E["auc"]["benchmarks_nonacc_twin"]))
m("RivTwinBeyond", fx(E["comparisons"]["twin_beyond_benchmarks_nonacc"]["diff"], 3))
m("RivTwinBeyondLo", fx(E["comparisons"]["twin_beyond_benchmarks_nonacc"]["ci"][0], 3))
m("RivTwinBeyondHi", fx(E["comparisons"]["twin_beyond_benchmarks_nonacc"]["ci"][1], 3))
m("RivEv", big(E["events"]))
m("RivN", big(E["n_test"]))

# ------------------------------------------------------------------ walk-forward choices of tau and lambda (v3-wf)
sel = X["selection"]
taus = [v for v in sel["tau"].values()]
m("SelYears", f"{min(sel['tau'])}--{max(sel['tau'])}")
m("SelTauMode", fx(max(set(taus), key=taus.count)))
m("SelTauFirst", r"$\infty$" if not np.isfinite(sel["tau"][min(sel["tau"])]) else fx(sel["tau"][min(sel["tau"])]))
lams = list(sel["lambda"].values())
m("SelLamMin", fx(min(lams), 1))
m("SelLamMax", fx(max(lams), 1))

# ------------------------------------------------------------------ provenance
pr = R["provenance"]
m("SnapDigest", pr["snapshot_digest"][:16])
m("LockDigest", pr["uv_lock_sha256"][:12])

# ------------------------------------------------------------------ added after the referee round
# the tails of the CFO errors and the cases that drive S1's mean difference
TL = X["tails"]
for key, tag in (("v2-pre", "Vtwopre"), ("v3", "Vthreedef"), ("v3-wf", "Vthree")):
    t = TL[key]
    m(f"TailMean{tag}", fx(t["mean"], 1))
    m(f"TailQnn{tag}", fx(t["q99"], 0))
    m(f"TailQnnn{tag}", big(round(t["q999"])))
    m(f"TailMax{tag}", big(round(t["max"])))
    m(f"TailThousand{tag}", t["n_gt_1000"])
lines = [r"\begin{tabular}{lrrrrrr}", r"\toprule",
         r"Specification & Median & Mean & 99th pct. & 99.9th pct. & Maximum & Firm-years $>$ 1{,}000 \\", r"\midrule"]
for key, label in (("v2-pre", "v2-pre"), ("v3", "v3, default"), ("v3-wf", "v3")):
    t = TL[key]
    lines.append(f"{label} & {fx(t['median'], 1)} & {fx(t['mean'], 1)} & {fx(t['q99'], 0)} & {big(round(t['q999']))} & "
                 f"{big(round(t['max']))} & {t['n_gt_1000']} \\\\")
lines += [r"\midrule", r"\multicolumn{7}{l}{Largest increases in absolute error, v3 against v2-pre} \\",
          r"Firm & Cutoff year & v3 & v2-pre & & & \\", r"\midrule"]
for c in TL["top_cases"][:8]:
    nm = c["name"].split(" /")[0]
    nm = (nm.title() if nm.isupper() else nm).replace("&", r"\&")
    lines.append(f"{nm} & {c['year']} & {big(round(c['v3']))} & {big(round(c['v2_pre']))} & & & \\\\")
lines += [r"\bottomrule", r"\end{tabular}"]
table("rev3_tails", lines)
m("TailTopShare", pct(TL["top20_share_of_mean_diff"], 0))
m("TailTrimDiff", fx(TL["mean_diff_trim999"]))
m("TailTopName", TL["top_cases"][0]["name"])
m("TailTopYear", TL["top_cases"][0]["year"])
m("TailTopErr", big(round(TL["top_cases"][0]["v3"])))

# the combination gain on raw (unwinsorized) absolute loss, and the sign test over years
raw = g["dm_abs_raw"]
m("GainRawMean", fx(-raw["mean"], 1))  # dm_abs_raw.mean < 0: the combination is WORSE on raw loss; this is "worse by"
m("GainRawP", pv(raw["p"]))
npos, ny = g["positive_years"], g["n_years"]
m("GainSignP", pv(sum(comb(ny, j) for j in range(npos, ny + 1)) / 2 ** ny))
m("FcfGainPos", gf["positive_years"])

# the logit against climatology, log scores, and the number of year blocks in each B2 cell
cl = c8["twin"]["murphy"]["uncertainty"]
m("ShortClim", fx(cl, 3))
m("ShortLogitClimBss", fx(1 - c8["logit"]["brier"] / cl, 3))
m("ShortLogTwin", fx(c8["twin"]["log"]))
m("ShortLogLogit", fx(c8["logit"]["log"]))
m("ShortBlocksFour", len(L["shortfall"]["4"]["recession"]["years"]))
m("ShortBlocksEight", len(L["shortfall"]["8"]["recession"]["years"]))
cells = [1 - L[a][k][sc]["twin"]["brier"] / L[a][k][sc]["logit"]["brier"] for a in ("shortfall", "credit_event")
         for k in ("4", "8") for sc in ("realized_shock", "recession")]
m("ShortCellsMax", fx(max(cells)))
m("ShortCellsMin", fx(min(cells)))
m("CeEvDelist", big(C["delist8"]["events"]))
m("CeAucTwinLo", fx(C["ce8"]["twin"]["ci"][0]))
m("CeAucTwinHi", fx(C["ce8"]["twin"]["ci"][1]))
m("CeAucZLo", fx(C["ce8"]["altman_z2"]["ci"][0]))
m("CeAucZHi", fx(C["ce8"]["altman_z2"]["ci"][1]))
m("BkEvThree", big(C["bk8"]["events"]))
m("BkNThree", big(C["bk8"]["n"]))

# the ladder sample: walk-forward and default v3 differ in the other direction from the full sample
m("LadThreeWf", fx(lad["v3-wf"]["mae"]["T1"]))
m("LadThreeDef", fx(lad["v3"]["mae"]["T1"]))
m("LadElastWf", fx(lad["v3-wf"]["elasticity_ratio"]))
m("FullThreeWf", fx(sp["v3-wf"]["mae"]["T1"], 3))
m("FullThreeDef", fx(sp["v3"]["mae"]["T1"], 3))
m("LadPreExact", fx(lad["v2-pre"]["mae"]["T1"]))
m("LadOneDrop", fx(lad["v2-pre+F5+F4"]["mae"]["T1"] - lad["v2-pre+F5+F4+F1"]["mae"]["T1"], 1))
m("LadTotalDrop", fx(lad["v2-pre"]["mae"]["T1"] - lad["v3"]["mae"]["T1"], 1))

m("SOneMedVtwoR", fx(S1["median_own"]["v2-pre"], 1))
m("SOneMedVthreeR", fx(S1["median_own"]["v3-wf"], 1))
m("HolmWeak", fx(R["plan2"]["holm"]["bankruptcy_weak_twin_minus_formula"]))

# the two code digests recorded with the results
pc = R["provenance_code"]
m("ShardDigest", pc["shard_digest"][:12])
m("AnalysisDigest", pc["analysis_digest"][:12])

# ------------------------------------------------------------------ the two pillars for the dashboard's evidence page
web = {
    "spec": pr["spec"], "snapshot_digest": pr["snapshot_digest"],
    "s1": {"median_v3": S1["median_own"]["v3-wf"], "median_v2_pre": S1["median_own"]["v2-pre"], "ci": S1["decision"]["ci"],
           "years_negative": S1["years_negative"], "years": S1["decision"]["G"], "success": S1["success"]},
    "elasticity": {"ratio": ov["ratio"], "range": [0.8, 1.25], "success": bool(0.8 <= ov["ratio"] <= 1.25)},
    "specs": {k: {"median_twin": v["mae"]["T1"], "median_16q": v["mae"]["N3"], "elasticity": v["elasticity_ratio"]}
              for k, v in sp.items()},
    "combination_gain_pct": g["gain_pct"], "combination_gain_ci": g["gain_pct_ci_year_block"],
    "density": {"coverage90": dc["coverage90_twin"], "crps": dc["crps"],
                "success": bool(dc["vs_gaussian"]["success"] or dc["vs_empirical"]["success"])},
    "shortfall": {"brier_twin": c8["twin"]["brier"], "brier_logit": c8["logit"]["brier"],
                  "bss": 1 - c8["twin"]["brier"] / c8["logit"]["brier"], "ci": P["year_block_ci"], "success": bool(P["success"])},
    "credit_events": {k: {s: C[k][s]["auc"] for s in ("twin", "pb_base", "altman_z2")} for k in ("bk8", "ce8")},
}
(ROOT / "web" / "public" / "data" / "research_rev3.json").write_text(json.dumps(web), encoding="utf-8")

out = ["% generated by engine/scripts/rev3_assets.py from research.json and rev3/inputs.json"]
out += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
(PAPER / "rev3_numbers.tex").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"rev3_numbers.tex: {len(macros)} macros; tables rev3_specs, rev3_ladder, rev3_family, rev3_density, rev3_shortfall, rev3_credit")
