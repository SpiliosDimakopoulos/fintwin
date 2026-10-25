# Roadmap

Where FinTwin is going, and where help is most welcome. The research items come from what the paper found does *not* work yet ([docs/paper/fintwin.pdf](docs/paper/fintwin.pdf), "Where it fails" in the README).

## Research directions

- **Operating leverage by industry.** The twin's cash flow reacts to revenue about 2.3× as much as firms' does. A single fixed-cost prior fixes much of it; priors estimated per industry, or per firm with shrinkage, may fix more.
- **Feedback loops that matter.** Two of the four loops have no measurable effect. Either find the setting where they do, or simplify the model.
- **Intervals in a regime break.** Conformal revenue intervals reach 90% coverage except in the 2020 stress quarters (77%). Methods that adapt faster to a break are an open question.
- **Beyond the 16-quarter margin.** The twin's value is in the direction of its departures from a long-window margin. Better ways to combine the two are welcome.
- **Other markets.** The pipeline reads US SEC XBRL. IFRS filings (e.g. ESEF in the EU) would test whether the results travel.

## Engineering

- More stress presets, starting with a 2008-style crisis ([#5](https://github.com/SpiliosDimakopoulos/fintwin/issues/5)).
- Test coverage for smaller modules and the TypeScript views.
- Dashboard accessibility, export of simulation results, mobile layout.

Look for issues labelled [`good first issue`](https://github.com/SpiliosDimakopoulos/fintwin/labels/good%20first%20issue) or [`help wanted`](https://github.com/SpiliosDimakopoulos/fintwin/labels/help%20wanted), or propose something in [Discussions](https://github.com/SpiliosDimakopoulos/fintwin/discussions).
