# Citation audit (wave 2, researcher agent, 28 Oct 2026)

`references.bib` has 70 entries.
- 12 entries were checked against Crossref. The classics were checked from memory.
- No fabricated entries were found. `bhatia2026` (SSRN 10.2139/ssrn.6871578) and `westphal2024` (Controlling & Management Review 68(4)) are real.

## Problems
| ID | Key | Issue | Fix |
|---|---|---|---|
| C1 | cameron2008 | Cited at `fintwin.tex:128` for two-way clustering, but the 2008 paper is about the wild-cluster bootstrap. | Cite `cameron2011` (multiway clustering) at line 128. Keep 2008 only where a wild bootstrap is used. Optionally add Thompson 2011 (JFE 99(1)), which is unverified. |
| C2 | chychyla2015 | The pages should be 37-72, and the DOI 10.2308/isys-50922 is missing. The entry is also uncited. | Fix it or delete it. |
| C3 | lyytinen2023 | The key says 2023 but the year field says 2024 (J. Organization Design 13(3) 77-93). | Make the two consistent. |
| C4 | altman2006 | A textbook is cited for Z''. | Add a primary source (Altman 1993/2000, or Altman-Hartzell-Peck 1995, unverified). |
| C5 | zmijewski1984 | No number field. | Add `number={Supplement}`. |
| C6 | uncited | bharath2008, borio2014, hanley1982, chychyla2015, fintwin_code, duffie2007, fama1997 and smith2009 are never cited. | Cite them where they fit (borio2014 and duffie2007 at `framework.tex:9`, smith2009 at `framework.tex:37`), or delete them. |
| C7 | reverse stress | `model.tex:58` has no citation. | Grundke-Pliszka 2018 is a candidate (unverified). |
| C8 | practitioner sources | bhatia2026 and westphal2024 are weak. They are acceptable only because the text labels them practitioner or early-stage work. | Keep the label. |

The other cite-to-claim checks passed: COVID, encompassing, combination, regime, real-time data, Sobol and conformal.

## Missing references to add
Gneiting-Raftery 2007, Campbell et al. 2008 and Shumway 2001 are already in the bib.

Chen et al. 2022: the author first names come from memory and must be checked. Gu-Kelly-Xiu 2020 (RFS) and Cao-You 2024 (FAJ) are unverified candidates.

```bibtex
@article{stein2001,
  author = {Stein, Jeremy C. and Usher, Stephen E. and LaGattuta, Daniel and Youngen, Jeff},
  title = {A Comparables Approach to Measuring Cashflow-at-Risk for Non-Financial Firms},
  journal = {Journal of Applied Corporate Finance}, volume = {13}, number = {4}, pages = {100--109}, year = {2001},
  doi = {10.1111/j.1745-6622.2001.tb00430.x}}
@article{hillegeist2004,
  author = {Hillegeist, Stephen A. and Keating, Elizabeth K. and Cram, Donald P. and Lundstedt, Kyle G.},
  title = {Assessing the Probability of Bankruptcy},
  journal = {Review of Accounting Studies}, volume = {9}, number = {1}, pages = {5--34}, year = {2004},
  doi = {10.1023/B:RAST.0000013627.90884.b7}}
@article{acharya2014,
  author = {Acharya, Viral and Engle, Robert and Pierret, Diane},
  title = {Testing Macroprudential Stress Tests: The Risk of Regulatory Risk Weights},
  journal = {Journal of Monetary Economics}, volume = {65}, pages = {36--53}, year = {2014},
  doi = {10.1016/j.jmoneco.2014.04.014}}
@article{hansen2011,
  author = {Hansen, Peter R. and Lunde, Asger and Nason, James M.},
  title = {The Model Confidence Set},
  journal = {Econometrica}, volume = {79}, number = {2}, pages = {453--497}, year = {2011},
  doi = {10.3982/ECTA5771}}
@article{hansen2005,
  author = {Hansen, Peter Reinhard},
  title = {A Test for Superior Predictive Ability},
  journal = {Journal of Business \& Economic Statistics}, volume = {23}, number = {4}, pages = {365--380}, year = {2005},
  doi = {10.1198/073500105000000063}}
@article{romano2005,
  author = {Romano, Joseph P. and Wolf, Michael},
  title = {Stepwise Multiple Testing as Formalized Data Snooping},
  journal = {Econometrica}, volume = {73}, number = {4}, pages = {1237--1282}, year = {2005},
  doi = {10.1111/j.1468-0262.2005.00615.x}}
@article{cameron2011,
  author = {Cameron, A. Colin and Gelbach, Jonah B. and Miller, Douglas L.},
  title = {Robust Inference With Multiway Clustering},
  journal = {Journal of Business \& Economic Statistics}, volume = {29}, number = {2}, pages = {238--249}, year = {2011},
  doi = {10.1198/jbes.2010.07136}}
@article{ball2022,
  author = {Ball, Ray and Nikolaev, Valeri V.},
  title = {On Earnings and Cash Flows as Predictors of Future Cash Flows},
  journal = {Journal of Accounting and Economics}, volume = {73}, number = {1}, pages = {101430}, year = {2022},
  doi = {10.1016/j.jacceco.2021.101430}}
@article{chen2022,
  author = {Chen, Xi and Cho, Yang Ha (Tony) and Dou, Yiwei and Lev, Baruch},
  title = {Predicting Future Earnings Changes Using Machine Learning and Detailed Financial Data},
  journal = {Journal of Accounting Research}, volume = {60}, number = {2}, pages = {467--515}, year = {2022},
  doi = {10.1111/1475-679X.12429}}
```
