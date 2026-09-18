# nfl-tools

A collection of NFL analytics, betting, projection, and content-generation tools built for **First & Thirty**.

The repository contains independent utilities for analyzing betting markets, building power ratings, evaluating player props, processing projection and PFF data, and generating weekly NFL content.

Most tools are designed to be run independently while sharing a common philosophy: **use market data, multiple independent data sources, and reproducible analysis rather than relying on subjective handicapping.**

## Projects

### Power Ratings

Builds weekly NFL power ratings by combining multiple independent estimates of team strength.

Current inputs include:

* Betting market ratings
* PFF
* ESPN FPI
* FTN/DAVE

The system normalizes the different rating scales before combining them and also measures **source agreement** to identify teams where the underlying models strongly agree or disagree.

Outputs are used for the weekly First & Thirty Power Ratings.

---

### Player Props

Tools for collecting projections, building player-prop models, identifying potential bets, and tracking results.

Markets currently under development or evaluation include:

* Passing yards
* Rushing yards
* Receiving yards
* Alternate player-prop lines

The pipeline is designed around frozen weekly snapshots so that projections, odds, model configuration, and eventual results can be evaluated without hindsight contamination.

Projection sources may include:

* PFF
* FantasyPros
* FTN
* 4for4
* FantasyPoints

Models and filters are evaluated through historical backtests and prospective tracking before being trusted for betting decisions.

---

### Odds Scanner

Scans sportsbook player-prop markets for pricing disagreements.

The scanner compares prices across sportsbooks, converts odds into implied probabilities, removes vig where appropriate, and searches for situations where Massachusetts-available sportsbooks differ materially from the broader market.

Supported Massachusetts books include:

* DraftKings
* FanDuel
* BetMGM
* Fanatics
* Caesars
* theScore Bet

The goal is not simply to find different prices. It is to identify situations where a locally available price may represent meaningful value relative to the broader betting market.

---

### NFL Line Shop

Collects NFL point spreads and produces an easy-to-read comparison of available lines across sportsbooks.

The tool:

* Pulls current NFL spreads
* Restricts results to relevant upcoming games
* Compares prices across books
* Highlights the best and worst available numbers
* Generates an HTML email report

This makes it easier to identify meaningful differences between sportsbooks without manually checking every book.

---

### PFF Content

Processes weekly PFF data and turns a large dataset into useful NFL analysis and content ideas.

The project includes tools for:

* Data normalization
* Metric discovery
* Leaderboards
* Scatter plots and visualizations
* Automated content discovery

Examples of analysis include:

* QB pressure performance
* Blitz rates
* Time to throw
* Turnover-worthy plays
* Target earners
* YAC per attempt
* Offensive-line pressures
* Pass-rush productivity
* Run stops
* Coverage performance
* Rookie performance
* Team man/zone tendencies

The goal is to make interesting performances and statistical outliers easier to discover without manually searching through hundreds of PFF fields every week.

---

### Weekly Recap

Generates a weekly recap of First & Thirty betting results.

The utility reads graded bets and produces a publishable HTML recap summarizing weekly performance.

Keeping this process separate from the betting models allows results to be reported consistently without altering the underlying historical records.

---

### Market Diagnostics

Research tools for evaluating whether betting signals actually contain predictive value.

Diagnostics can be used to examine:

* ROI
* Sample size
* Holdout performance
* Market-specific performance
* Threshold sensitivity
* Filters
* Historical versus prospective results

The emphasis is on separating **interesting historical patterns** from signals that have enough evidence to justify prospective use.

## Repository Philosophy

This repository is intentionally research-oriented.

A model performing well historically does not automatically make it a betting strategy. Whenever possible, the workflow separates:

**Discovery → Backtest → Holdout Validation → Prospective Tracking → Deployment**

Data and model configurations are frozen when possible so results can be reproduced later and evaluated honestly.

## Repository Structure

The repository contains several largely independent projects:

```text
nfl-tools/
│
├── pff_content/
│   └── PFF data analysis and content discovery
│
├── player_props/
│   └── Player projection and prop modeling
│
├── odds_scanner/
│   └── Sportsbook price and market disagreement scanner
│
├── weekly_recap/
│   └── Weekly betting-results recap generator
│
├── market_diagnostics/
│   └── Model and betting-market evaluation tools
│
└── ...
```

Individual projects may contain their own README files with more detailed setup and usage instructions.

## Technology

Most utilities are written in **Python** and are designed to run locally.

Common components include:

* Python 3
* pandas
* CSV/JSON data pipelines
* HTML report generation
* Sportsbook APIs
* Projection datasets
* PFF data exports

Some projects require API credentials or paid third-party data subscriptions. Credentials and proprietary datasets are intentionally excluded from the repository.

## First & Thirty

These tools support research and content published by **First & Thirty**, an independent NFL analytics and betting project.

The repository is primarily intended to make the analysis behind the site reproducible, testable, and easier to maintain throughout the NFL season.

## Disclaimer

This repository is for analytical and informational purposes.

Sports betting involves risk. Historical model performance does not guarantee future results.
