// Encyclopedia content. Each article = metadata + a Markdown body (rendered by
// components/encyclopedia/Markdown, with [[fig:KEY]] figure markers) + a 10-question quiz.
// Sections group articles in the sidebar; quiz scores are stored per section on the account.

const monteCarlo = {
  key: 'monte-carlo',
  title: 'Monte-Carlo Simulation',
  section: 'finance',
  sectionLabel: 'Quantitative Finance',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'Estimate the whole distribution of profit — and its risk — by sampling thousands of random scenarios.',
  body: `# Monte-Carlo Simulation

**Monte-Carlo simulation** estimates the *distribution* of an uncertain outcome by drawing
thousands of random scenarios from a model of the inputs and computing the result for each.
Instead of a single "expected profit" number you get the whole shape of what could happen —
and with it, *risk*.

> In one line: replace each uncertain input with a probability distribution, sample it many
> times, and let the histogram of results answer your question.

## Why use it for manufacturing profit?

A build's profit depends on many uncertain things at once: material buy prices, the product's
sell price, how fast you can fill orders (liquidity), the bid/ask spread, taxes and broker
fees, and logistics delays. A deterministic calculator gives you one profit for one set of
assumptions. Monte-Carlo asks: *given how those inputs actually move, how likely is a loss,
and how bad could it get?*

[[fig:histogram|A simulated profit distribution — each run is one sampled scenario. Markers show the mean E[Profit], the 5% Value-at-Risk, and break-even.]]

## The recipe

- **Model the inputs.** Each price gets a distribution (lognormal, or an *empirical* one
  fitted to market history). Volumes, spreads and delays get their own.
- **Add dependence.** Prices move *together*. A **correlation matrix** (or factor model) plus
  a **copula** tie the random draws so a market-wide move hits several materials at once.
- **Draw a scenario.** Sample one value for every input.
- **Price the P&L.** Compute \`revenue − material cost − taxes − fixed cost − logistics\` for
  that draw.
- **Repeat** N times and collect the results.

## Reading the output

- **E[Profit]** — the mean; your best single estimate of the average outcome.
- **Median** — the middle outcome; differs from the mean when the distribution is skewed.
- **σ (standard deviation)** — dispersion; bigger σ = more uncertain.
- **VaR 5% / 1%** — *Value-at-Risk*: the loss you would not exceed with 95% / 99% confidence.
  A VaR 5% of −250M means "5% of the time, profit is worse than −250M".
- **CVaR 5%** (*expected shortfall*) — the *average* outcome inside that worst 5% tail; always
  at least as pessimistic as VaR and a truer picture of tail pain.
- **P(loss)** — the fraction of scenarios with profit below zero.
- **Percentiles** — p5…p95 sketch the whole range, not just the average.

> The mean tells you the *reward*; σ, VaR, CVaR and P(loss) tell you the *risk*. A high
> E[Profit] with a fat left tail can still be a bad bet.

## How many runs? Convergence and Monte-Carlo error

Every metric from a finite sample carries sampling noise. That error shrinks like **1/√N**:
to halve it you need roughly **four times** the runs. The engine reports a 95% **confidence
interval** (via *batch means*) and a **relative MC error**; when the interval is tight
relative to E[Profit], the run has *converged*.

[[fig:convergence|As iterations grow the estimate settles toward the true value and the 95% confidence band narrows like 1/√N.]]

## Distributions, correlation and tail dependence

The marginal distribution sets *how* one price wanders; the **copula** sets *how prices move
together*. A **Gaussian copula** makes joint extremes rare; a **Student-t copula** adds **tail
dependence** — crashes (and spikes) that hit many assets at the same time, which is exactly
what real market stress looks like.

[[fig:copula|Same correlation, different copula. The Student-t copula adds the joint tail events (red) a Gaussian copula misses.]]

## Two refinements (and their traps)

- **Anchoring.** A risk sim must be *centred on the deterministic price the plan actually
  used*, with history supplying only the *shape* (volatility). Sampling raw history levels
  instead biases the mean and can make a profitable build look like a near-certain loss.
- **Price paths.** Over a holding horizon you can model a *path* (AR(1) mean-reversion,
  optionally with GARCH volatility clustering). Exponentiating a drift-free log-price inflates
  the mean (volatility drag / Jensen's inequality), so a **martingale correction** — subtract
  ½σ² per step — keeps the average on the anchor.

## In IndyOps

Toggle **🎲 Simulations** on the Calculator or Chain tab. The Monte-Carlo panel shows the
profit distribution, the full risk-metric set, a cost breakdown, percentiles and a convergence
indicator. It is the *stochastic* counterpart to the deterministic build cost — and the
foundation the **Scenario Simulation** builds on.`,
  quiz: [
    { q: 'What does a Monte-Carlo simulation primarily estimate?', answer: 2,
      options: ['The exact future price', 'The blueprint ME', 'The distribution of possible outcomes', 'A single guaranteed profit'],
      explain: 'You get the whole distribution (and its risk), not one number.' },
    { q: 'A VaR 5% of −250M ISK means…', answer: 1,
      options: ['You always lose 250M', '5% of scenarios are worse than −250M', 'The average loss is exactly 250M', 'Profit is +250M 5% of the time'] },
    { q: 'CVaR (expected shortfall) relative to VaR is…', answer: 3,
      options: ['Identical to VaR', 'Always less pessimistic', 'Unrelated to the tail', 'The mean of the worst tail beyond VaR (≥ as pessimistic)'] },
    { q: 'Monte-Carlo sampling error shrinks approximately like…', answer: 0,
      options: ['1/√N', '1/N', 'N', 'It stays constant'] },
    { q: 'A copula in this model captures…', answer: 1,
      options: ['The tax rate', 'How variables move together (dependence)', 'The histogram bin width', 'One price’s marginal only'] },
    { q: 'Tail dependence (Student-t copula) represents…', answer: 2,
      options: ['Lower volatility', 'Zero correlation', 'Simultaneous extreme moves across assets', 'Fully independent prices'] },
    { q: 'P(loss) is…', answer: 3,
      options: ['The mean profit', 'The Value-at-Risk', 'The bid/ask spread', 'The fraction of scenarios with profit < 0'] },
    { q: 'Why anchor the simulation to the plan’s deterministic price?', answer: 1,
      options: ['To make it run slower', 'So the mean isn’t biased away from the price actually paid', 'To force a larger σ', 'There is no reason'] },
    { q: 'The −½σ² (martingale) correction on a log-price path prevents…', answer: 2,
      options: ['Negative prices', 'Correlation between assets', 'Inflation of E[price] from exponentiation (volatility drag)', 'The run from converging'] },
    { q: 'To roughly halve Monte-Carlo error you should…', answer: 0,
      options: ['Quadruple the iterations', 'Halve the iterations', 'Double the iterations', 'Nothing — it can’t change'],
      explain: 'Error ∝ 1/√N, so 4× the runs ≈ half the error.' },
  ],
}

const scenarios = {
  key: 'scenarios',
  title: 'Scenario Simulation',
  section: 'finance',
  sectionLabel: 'Quantitative Finance',
  level: 'Advanced',
  difficulty: 3,
  summary: 'Deterministic stress tests: impose specific "what-if" futures and compare each against the baseline.',
  body: `# Scenario Simulation

Where Monte-Carlo asks *"given normal randomness, what's the distribution?"*, **scenario
simulation** asks a sharper question: *"what happens **if** this specific thing occurs?"* It is
deterministic **stress testing** — you define concrete "what-if" futures, measure how a build
performs under each, and compare against the baseline.

> Monte-Carlo = stochastic uncertainty around today. Scenario simulation = specific, named
> futures (a shock, a tax change, a demand shift) you deliberately impose.

## A scenario is a transform of the inputs

Each scenario is a vector of shifts applied to the simulation's inputs:

- raw-material prices ↑/↓, product price ↑/↓
- volatility, market volume (liquidity), bid/ask spread
- production cost, taxes (sales + broker), logistics cost & delays
- manufacturing time, slot count

Apply the shifts, then run the **same Monte-Carlo engine** under the new inputs. So every
scenario still yields the full risk set (E[Profit], VaR, CVaR, P(loss)) — which is what lets
you *compare* it to the baseline.

[[fig:scenarioShift|A stress scenario shifts the whole profit distribution left and widens it: lower expected profit, fatter loss tail.]]

## Scenario categories

- **Exogenous** — external market events: market shock, resource shortage, industry
  disruption, tax increase/reduction, inflation.
- **Logistics** — hauling-cost spike, logistics disruption (delays), freighter-risk increase.
- **Market demand** — capital-meta shift, T2 boom, recession.
- **Counterfactual** — "what if taxes were 50% lower?", "what if Jita rose 20%?".
- **Endogenous** — your own decisions: production expansion, vertical integration, market
  concentration. (In IndyOps these are *parameter approximations* — they shift inputs rather
  than re-solving the build.)

## Outputs: always vs the baseline

For each scenario the engine reports the absolute and percentage **profit change**, the **risk
change** (Δσ, ΔVaR), the **ROI change**, and a **viability** flag (profitable *and* P(loss) <
50%). The signal is the *delta*, not the scenario's number in isolation.

[[fig:scenarioBars|Baseline expected profit indexed to 100, with each scenario beside it — green improves, red erodes.]]

## Composite stress tests

Real stress is rarely one thing. **Composite scenarios** combine shifts — e.g. *Market Shock +
Resource Shortage + Hauling Spike* — by multiplying the multipliers and adding the additive
terms, exposing interactions a single-factor test misses.

## Ranking and sensitivity

With many scenarios you need to *rank* strategies. A **risk-adjusted score** standardises each
metric (z-score) and weights expected profit, Sharpe-like ratio, VaR, return-per-slot,
return-per-hour and probability of loss into one number.

A **tornado chart** sorts scenarios by the magnitude of their profit impact — the widest bars
are the risks that matter most. That is **sensitivity analysis**: which assumption, if wrong,
hurts the most?

[[fig:tornado|A sensitivity tornado: scenarios sorted by |Δ profit|. The widest bars dominate the build’s risk.]]

## Why professionals stress-test

Banks and funds are *required* to stress portfolios against severe-but-plausible scenarios
(rate shocks, liquidity crises) precisely because averages hide tail risk. **Reverse stress
testing** flips the question — *what scenario would make this build unprofitable?* — which is
exactly what the counterfactual scenarios answer.

## In IndyOps

After a calc, open the **🧪 Scenario Simulation** panel. Pick predefined scenarios, combine
them into a composite, or build a custom one; run the analysis for the comparison table,
profit-change bars, the sensitivity tornado, the strategy ranking and a PDF report. Endogenous
scenarios are labelled as parameter approximations.`,
  quiz: [
    { q: 'How does scenario simulation differ from Monte-Carlo?', answer: 2,
      options: ['It is faster only', 'It ignores risk', 'It evaluates specific deterministic "what-if" futures', 'It is fully random'] },
    { q: 'In this engine a scenario is implemented as…', answer: 0,
      options: ['A transform/shift of the simulation inputs', 'A brand-new blueprint', 'A tax form', 'A histogram'] },
    { q: '"Counterfactual" scenarios are…', answer: 3,
      options: ['Endogenous decisions', 'Future forecasts', 'Random draws', 'Alternative what-ifs like "taxes 50% lower"'] },
    { q: 'Endogenous scenarios model…', answer: 1,
      options: ['External market shocks', 'Your own decisions (expansion, integration)', 'Tax legislation', 'The weather'] },
    { q: 'The key signal from a scenario is…', answer: 2,
      options: ['Its absolute profit only', 'The random seed', 'The change (delta) vs the baseline', 'The blueprint ME'] },
    { q: 'A composite stress test…', answer: 1,
      options: ['Runs exactly one factor', 'Combines several shifts into one scenario', 'Always lowers risk', 'Is purely random'] },
    { q: 'A tornado chart shows…', answer: 3,
      options: ['Wind speed', 'The price path', 'The correlation matrix', 'Scenarios sorted by magnitude of profit impact'] },
    { q: '"Viable" in the comparison means…', answer: 0,
      options: ['E[Profit] > 0 and P(loss) < 50%', 'Any profit at all', 'ROI above 100%', 'Zero risk'] },
    { q: 'Reverse stress testing asks…', answer: 2,
      options: ['What is the median?', 'How many runs are needed?', 'What scenario would make the build unprofitable?', 'What is the average?'] },
    { q: 'Relative to Monte-Carlo, scenario simulation is best seen as…', answer: 1,
      options: ['A full replacement', 'A complement — deterministic stress on the stochastic baseline', 'Unrelated', 'Only useful for ships'] },
  ],
}

export const ARTICLES = [monteCarlo, scenarios]

// articles grouped by section (for the sidebar)
export const SECTIONS = ARTICLES.reduce((acc, a) => {
  const s = acc.find(x => x.section === a.section)
  if (s) s.articles.push(a)
  else acc.push({ section: a.section, label: a.sectionLabel, articles: [a] })
  return acc
}, [])
