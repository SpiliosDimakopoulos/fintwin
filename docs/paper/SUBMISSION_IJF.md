# Submission package: International Journal of Forecasting

The journal's Guide for Authors was read on 16-11-2026 (ScienceDirect). The journal uses double-anonymized review
and Editorial Manager.

## Files to upload

| File | Build | Contents |
|---|---|---|
| `title_page.pdf` | `latexmk -pdf title_page.tex` | Title, author, address, e-mail, acknowledgements, competing interest, funding, CRediT, the identifying links |
| `fintwin_anon.pdf` | `latexmk -pdf fintwin_anon.tex` | Anonymized manuscript (double spaced; no name, links or self-identifying citation) |
| `fintwin_supplement.pdf` | `latexmk -pdf fintwin_supplement.tex` | Online supplement (material of the earlier evaluation) |
| `highlights.txt` | — | 5 highlights, each at most 85 characters |
| `cover_letter.pdf` | `latexmk -pdf cover_letter.tex` | Cover letter |
| LaTeX source | `engine/scripts/arxiv_bundle.py` | Editable source, as the journal requires for typesetting |
| Declaration of interest | Elsevier's online tool | The journal asks for its .docx tool output. **The author fills it in at submission** (content as on the title page) |

## Checklist against the guide

- [x] Corresponding author with e-mail and postal address (city and country, as the author chose)
- [x] Abstract of 100–150 words (150), with no references or notation
- [x] At least five keywords (7), none repeating a title word
- [x] Highlights (5, at most 85 characters each)
- [x] Double-anonymized: separate title page; the manuscript and its PDF metadata contain no author name, e-mail or link
- [x] Generative-AI declaration, under the journal's section title, before the references
- [x] Competing interest (authorship of the software), funding and CRediT, on the title page
- [x] Data and code availability (links on the title page; in the manuscript they are withheld for review)
- [x] Prior dissemination and similar work disclosed (cover letter; earlier evaluation cited)
- [x] References in author-year style (elsarticle-harv). Every cited entry is in the reference list. 23 uncited bib
      entries are ignored by BibTeX.
- [x] Double spacing in the review version
- [ ] Declaration-of-interest .docx from Elsevier's tool: **the author does this at submission**
- [ ] Suggested reviewers (4–6): candidates below. **The author checks affiliations and e-mails on institutional
      pages and that there is no conflict**

## Suggested reviewers (candidates; verify before entering)

| Name | Affiliation (to verify) | Field, and the link to the paper |
|---|---|---|
| Andrew J. Patton | Duke University | Forecast evaluation and comparison of forecasts (MCS, encompassing, loss functions) |
| Peter Reinhard Hansen | University of North Carolina at Chapel Hill | Model confidence set and the test for superior predictive ability, both used in the paper |
| Jens Hilscher | University of California, Davis | Prediction of corporate distress (Campbell, Hilscher and Szilagyi 2008 is cited) |
| Stewart Jones | University of Sydney | Machine-learning distress prediction (Jones et al. 2017 is cited) |
| Kewei Hou | The Ohio State University | Cross-sectional earnings forecasts (Hou, van Dijk and Zhang 2012, the model behind the second model) |
| Suresh Nallareddy | Duke University | Cash-flow prediction from accounting data (Nallareddy et al. 2020 is cited) |

The guide asks for names, addresses and fields of interest of 4–6 people outside the author's institution. E-mail
addresses are not compiled here. Take them from each person's institutional page.

## Not done, needs the author

1. The Elsevier declaration-of-interest tool (.docx).
2. Checking the suggested reviewers and their e-mails.
3. Pressing submit in Editorial Manager.
