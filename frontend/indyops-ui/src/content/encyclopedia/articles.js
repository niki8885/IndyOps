// Encyclopedia content. Each article = metadata + a Markdown body (rendered by
// components/encyclopedia/Markdown, with [[fig:KEY]] figure markers) + a multi-question quiz.
// Sections group articles in the sidebar; quiz scores are stored per section on the account.
// Formulas are written as inline `code` (the renderer has no LaTeX); inner backticks are escaped.

const monteCarlo = {
  key: 'monte-carlo',
  title: 'Monte-Carlo Simulation',
  section: 'finance',
  sectionLabel: 'Quantitative Finance',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'Estimate the whole distribution of profit — and its risk — by sampling thousands of random scenarios. From the Law of Large Numbers to GBM, variance reduction and HPC.',
  body: `# Monte-Carlo Simulation

**Monte-Carlo simulation** estimates the *distribution* of an uncertain outcome by drawing
thousands of random scenarios from a model of the inputs and computing the result for each.
Instead of a single "expected profit" number you get the whole shape of what could happen —
and with it, *risk*.

> In one line: replace each uncertain input with a probability distribution, sample it many
> times, and let the histogram of results answer your question.

## From a single number to a distribution

A deterministic model maps fixed inputs to one output, \`Y = f(X)\`. But real inputs — prices,
rates, demand — are uncertain. Monte-Carlo replaces each fixed input with a *probability
distribution* and asks a richer question. Instead of *"what is the expected outcome?"* it
answers *"what is the entire distribution of possible outcomes?"*

## A little history

The method was developed in the 1940s on the Manhattan Project by **Stanislaw Ulam**, **John
von Neumann** and **Nicholas Metropolis**, and named after the Monte-Carlo casino for its
reliance on chance. Born for nuclear physics, it now underpins statistical mechanics,
engineering, economics, finance and machine learning.

## Why use it for manufacturing profit?

A build's profit depends on many uncertain things at once: material buy prices, the product's
sell price, how fast you can fill orders (liquidity), the bid/ask spread, taxes and broker
fees, and logistics delays. A deterministic calculator gives you one profit for one set of
assumptions. Monte-Carlo asks: *given how those inputs actually move, how likely is a loss,
and how bad could it get?*

[[fig:histogram|A simulated profit distribution — each run is one sampled scenario. Markers show the mean E[Profit], the 5% Value-at-Risk, and break-even.]]

## The recipe — five steps

- **1. Define the uncertain inputs** — material prices, sell price, volume, spread, costs, delays.
- **2. Assign each a distribution** — e.g. a price as lognormal \`LN(μ, σ²)\`, or an *empirical*
  distribution fitted to market history; a return as \`N(0.08, 0.15²)\` (8% mean, 15% vol).
- **3. Add dependence.** Prices move *together*. A **correlation matrix** (or factor model) plus
  a **copula** tie the random draws so a market-wide move hits several materials at once.
- **4. Draw a scenario and price the P&L** — sample one value for every input, then compute
  \`revenue − material cost − taxes − fixed cost − logistics\` for that draw.
- **5. Repeat N times and analyse** — collect the results into a distribution and read off the
  mean, spread, quantiles and tail risk.

## Mathematical foundations

A random input \`X\` is described by a distribution \`F(x)\` (Normal \`N(μ, σ²)\`, Uniform
\`U(a, b)\`, Lognormal \`LN(μ, σ²)\`, …). Its true mean is an integral that is often impossible
to evaluate by hand: \`E[X] = ∫ x·f(x) dx\`. Monte-Carlo sidesteps the integral by **averaging
samples**: \`Ê[X] = (1/N)·Σ Xᵢ\`.

Two theorems justify this:

- **Law of Large Numbers (LLN).** As \`N → ∞\` the sample mean converges to the true mean
  \`E[X]\` with probability 1. This is *why* the estimate is correct in the limit.
- **Central Limit Theorem (CLT).** For large \`N\` the estimation error is approximately normal:
  \`√N·(X̄ − E[X]) → N(0, σ²)\`. This is *why* we can wrap a **confidence interval** around the
  estimate and know how trustworthy it is.

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

Every metric from a finite sample carries sampling noise. By the CLT that error shrinks like
\`O(1/√N)\` — so to cut it by 10× you need about **100× the runs**, and to merely *halve* it you
need roughly **4× the runs**. The engine reports a 95% **confidence interval** (via *batch
means*) and a **relative MC error**; when the interval is tight relative to E[Profit], the run
has *converged*.

[[fig:convergence|As iterations grow the estimate settles toward the true value and the 95% confidence band narrows like 1/√N.]]

## Distributions, correlation and tail dependence

The marginal distribution sets *how* one price wanders; the **copula** sets *how prices move
together*. A **Gaussian copula** makes joint extremes rare; a **Student-t copula** adds **tail
dependence** — crashes (and spikes) that hit many assets at the same time, which is exactly
what real market stress looks like.

[[fig:copula|Same correlation, different copula. The Student-t copula adds the joint tail events (red) a Gaussian copula misses.]]

## Geometric Brownian Motion

Over a holding horizon you can model a price *path* rather than a single draw. The standard
model is **Geometric Brownian Motion**, the stochastic differential equation
\`dS = μ·S·dt + σ·S·dW\`, where \`μ\` is drift, \`σ\` is volatility and \`dW\` is a Wiener
(Brownian) increment. Its exact discrete step is
\`S(t+Δt) = S(t)·exp[(μ − ½σ²)·Δt + σ·√Δt·Z]\`, with \`Z ~ N(0, 1)\`.

The \`−½σ²\` term is not optional. Exponentiating a drift-free log-price would inflate the mean
(volatility drag / Jensen's inequality); subtracting \`½σ²\` per step is the **martingale
correction** that keeps the average on its anchor.

[[fig:gbmPaths|Many GBM paths from the same start fan out over time — variance grows like √t around the drift line.]]

> **Anchoring.** A risk sim must be *centred on the deterministic price the plan actually used*,
> with history supplying only the *shape* (volatility). Sampling raw history levels instead
> biases the mean and can make a profitable build look like a near-certain loss.

## Variance reduction — same accuracy, fewer runs

Because error falls only as \`1/√N\`, brute force is expensive. **Variance-reduction**
techniques get the same precision from far fewer paths:

- **Antithetic variates** — for every draw \`Z\` also use \`−Z\`; the negatively-correlated pair
  cancels noise.
- **Control variates** — subtract a correlated quantity whose mean you know exactly.
- **Importance sampling** — deliberately *oversample* rare-but-important events (deep losses),
  then re-weight, to price the tail with fewer wasted runs.
- **Quasi-Monte-Carlo** — replace pseudo-random \`U(0,1)\` draws with **low-discrepancy
  sequences** (Sobol, Halton, Faure) that cover the space more evenly and often converge faster.

## Markov Chain Monte Carlo (MCMC)

When you must sample from a complicated distribution you cannot draw from directly — typically a
Bayesian posterior — **MCMC** builds a Markov chain whose stationary distribution *is* the
target. **Metropolis-Hastings**, **Gibbs sampling** and **Hamiltonian Monte-Carlo** are the
workhorses, central to Bayesian statistics and machine learning.

## Cost and high-performance computing

Monte-Carlo is **embarrassingly parallel**: each path is independent, so the work splits cleanly
across cores and machines. Large simulations use **OpenMP** (across CPU cores), **MPI** (across
machines) and **GPUs** (CUDA / OpenCL / ROCm) to run thousands of paths at once — the standard
answer to the slow \`1/√N\` convergence.

## Limitations

- **Model risk** — the output is only as good as the model and its assumptions.
- **Distribution risk** — the wrong input distribution gives confidently wrong answers.
- **Rare events** — extreme tails need many runs or specialised methods (importance sampling).

## In IndyOps

Toggle **🎲 Simulations** on the Calculator or Chain tab. The Monte-Carlo panel shows the
profit distribution, the full risk-metric set, a cost breakdown, percentiles and a convergence
indicator. It is the *stochastic* counterpart to the deterministic build cost — and the
foundation the **Scenario Simulation** builds on.`,
  quiz: [
    { q: 'What does a Monte-Carlo simulation primarily estimate?', answer: 2,
      options: ['The exact future price', 'The blueprint ME', 'The distribution of possible outcomes', 'A single guaranteed profit'],
      explain: 'You get the whole distribution (and its risk), not one number.' },
    { q: 'The Law of Large Numbers guarantees that, as N grows, the sample average…', answer: 1,
      options: ['Oscillates forever', 'Converges to the true mean E[X] with probability 1', 'Diverges to infinity', 'Equals the median'],
      explain: 'The LLN is the reason the Monte-Carlo estimate is correct in the limit.' },
    { q: 'The Central Limit Theorem is what lets us…', answer: 3,
      options: ['Avoid sampling entirely', 'Remove all model risk', 'Make prices non-random', 'Put a confidence interval around the estimate'],
      explain: 'CLT: √N·(X̄ − E[X]) → N(0, σ²), so the estimator error is ~normal and quantifiable.' },
    { q: 'The Monte-Carlo estimator of E[X] is…', answer: 0,
      options: ['(1/N)·Σ Xᵢ — the sample average', 'max(Xᵢ)', 'The first draw X₁', 'The exact integral ∫ x·f(x) dx'],
      explain: 'It approximates the (often intractable) integral E[X] = ∫ x·f(x) dx by averaging samples.' },
    { q: 'A VaR 5% of −250M ISK means…', answer: 1,
      options: ['You always lose 250M', '5% of scenarios are worse than −250M', 'The average loss is exactly 250M', 'Profit is +250M 5% of the time'] },
    { q: 'CVaR (expected shortfall) relative to VaR is…', answer: 3,
      options: ['Identical to VaR', 'Always less pessimistic', 'Unrelated to the tail', 'The mean of the worst tail beyond VaR (≥ as pessimistic)'] },
    { q: 'Monte-Carlo sampling error shrinks approximately like…', answer: 0,
      options: ['1/√N', '1/N', 'N', 'It stays constant'] },
    { q: 'To cut the Monte-Carlo error by a factor of 10 you need roughly…', answer: 2,
      options: ['10× the runs', '√10× the runs', '100× the runs', 'No extra runs'],
      explain: 'Error ∝ 1/√N, so 10× accuracy needs 10² = 100× the iterations.' },
    { q: 'A copula in this model captures…', answer: 1,
      options: ['The tax rate', 'How variables move together (dependence)', 'The histogram bin width', 'One price’s marginal only'] },
    { q: 'Tail dependence (Student-t copula) represents…', answer: 2,
      options: ['Lower volatility', 'Zero correlation', 'Simultaneous extreme moves across assets', 'Fully independent prices'] },
    { q: 'In the GBM step S(t+Δt) = S(t)·exp[(μ − ½σ²)·Δt + σ·√Δt·Z], the −½σ² term…', answer: 2,
      options: ['Prevents negative prices', 'Adds correlation between assets', 'Corrects volatility drag so E[price] stays on the anchor', 'Stops the run converging'],
      explain: 'Without it, exponentiating a log-price inflates the mean (Jensen). It is the martingale correction.' },
    { q: 'Antithetic variates reduce variance by…', answer: 1,
      options: ['Adding more independent draws', 'Pairing each draw Z with −Z so noise cancels', 'Using a bigger σ', 'Dropping correlated inputs'] },
    { q: 'Importance sampling is used to…', answer: 3,
      options: ['Make the code shorter', 'Remove the need for distributions', 'Guarantee a profit', 'Oversample rare/tail events, then re-weight'],
      explain: 'It spends draws where they matter (the tail) and re-weights to stay unbiased.' },
    { q: 'Quasi-Monte-Carlo replaces pseudo-random draws with…', answer: 0,
      options: ['Low-discrepancy sequences (Sobol, Halton, Faure)', 'Larger random seeds', 'A single fixed value', 'Historical prices verbatim'],
      explain: 'Low-discrepancy sequences cover the space more evenly and often converge faster than 1/√N.' },
    { q: 'MCMC (Metropolis-Hastings, Gibbs, Hamiltonian) is mainly for…', answer: 2,
      options: ['Sorting scenarios', 'Speeding up matrix multiply', 'Sampling complex distributions you can’t draw from directly', 'Computing a single mean faster'] },
    { q: 'Monte-Carlo parallelises extremely well because…', answer: 1,
      options: ['Paths must run in strict order', 'Each path is independent (embarrassingly parallel)', 'It needs no random numbers', 'GPUs forbid it'],
      explain: 'Independence is why MPI / OpenMP / GPU acceleration works so cleanly here.' },
  ],
}

const scenarios = {
  key: 'scenarios',
  title: 'Scenario Simulation',
  section: 'finance',
  sectionLabel: 'Quantitative Finance',
  level: 'Advanced',
  difficulty: 3,
  summary: 'Deterministic stress tests: impose specific "what-if" futures and compare each against the baseline. State-space, scenario trees, stochastic programming and reverse stress testing.',
  body: `# Scenario Simulation

Where Monte-Carlo asks *"given normal randomness, what's the distribution?"*, **scenario
simulation** asks a sharper question — *what happens if this specific thing actually occurs?* It
is deterministic **stress testing**: you define concrete "what-if" futures, measure how a build
performs under each, and compare against the baseline.

> Monte-Carlo = stochastic uncertainty around today. Scenario simulation = specific, named
> futures (a shock, a tax change, a demand shift) you deliberately impose.

## State, transition and outcome

Formally a system is a **state vector** \`x = [x₁, x₂, …, xₙ]\` — prices, rates, inflation,
demand, costs — that evolves by a transition rule \`x(t+1) = f(x(t), u(t), ε(t))\`, where
\`u\` are your decisions and \`ε\` is random disturbance. A **scenario** \`sᵢ\` is one chosen
realisation of those drivers, e.g. \`sᵢ = { interest, inflation, GDP growth, demand }\`, and an
**outcome function** scores it: \`Yᵢ = F(sᵢ)\` — an NPV, a portfolio return, a VaR, a profit.

## A scenario is a transform of the inputs

In this engine each scenario is a vector of shifts applied to the simulation's inputs:

- raw-material prices ↑/↓, product price ↑/↓
- volatility, market volume (liquidity), bid/ask spread
- production cost, taxes (sales + broker), logistics cost & delays
- manufacturing time, slot count

Apply the shifts, then run the **same Monte-Carlo engine** under the new inputs. So every
scenario still yields the full risk set (E[Profit], VaR, CVaR, P(loss)) — which is what lets
you *compare* it to the baseline.

[[fig:scenarioShift|A stress scenario shifts the whole profit distribution left and widens it: lower expected profit, fatter loss tail.]]

## Three ways to build scenarios

- **Deterministic** — a few hand-designed futures (Optimistic / Base case / Recession). Easy to
  read and to discuss with stakeholders, but they cover only a sliver of the uncertainty space.
- **Stochastic generation** — draw the drivers from distributions (e.g. \`r ~ N(μ, σ²)\`) to make
  thousands of scenarios computationally. This is where scenario analysis meets Monte-Carlo.
- **Stress testing** — push a driver to an extreme-but-plausible level, \`x_stressed = x* + Δ\`
  (a 30% equity crash, an energy shock). Severe-but-plausible stress testing became a **central
  regulatory requirement after the 2008 crisis**, precisely because averages hide tail risk.

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

## Scenario trees and stochastic programming

When decisions unfold over *stages* — invest now, observe the market, invest again — the future
branches into a **scenario tree**: one root today, several states next period, each splitting
again. Every branch carries a probability \`P(sᵢ)\`, and the expected outcome is the
probability-weighted sum over leaves: \`E[Y] = Σ P(sᵢ)·Yᵢ\`. This is the backbone of
**stochastic programming**, used for asset-liability management, energy markets and inventory
optimisation.

[[fig:scenarioTree|A two-stage scenario tree: each branch is a future with a probability; outcomes Y sit at the leaves.]]

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

## Scenario vs Monte-Carlo — and combining them

They are complements, not rivals. Monte-Carlo samples *random* uncertainty around today's
assumptions; scenario simulation imposes *structured, named* futures. The professional workflow
uses both: **(1)** define macro scenarios, **(2)** run a full Monte-Carlo *inside each*, **(3)**
aggregate the results. You get both the specific story and its distribution of outcomes.

## Why professionals stress-test

Banks and funds are *required* to stress portfolios against severe-but-plausible scenarios
(rate shocks, liquidity crises) precisely because averages hide tail risk. **Reverse stress
testing** flips the question — *what scenario would make this build unprofitable?* — which is
exactly what the counterfactual scenarios answer.

## Modern developments

- **ML-assisted scenario generation** — Variational Autoencoders, GANs and diffusion models
  learn to generate realistic market states beyond hand-picked ones.
- **Agent-based simulation** — model interacting, heterogeneous market participants and let
  aggregate behaviour emerge.
- **High-performance computing** — MPI, OpenMP, GPUs and distributed cloud push scenario counts
  into the billions.

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
    { q: 'Formally, scoring a scenario sᵢ with an outcome function gives…', answer: 1,
      options: ['A random seed', 'Yᵢ = F(sᵢ) — a performance metric (NPV, profit, VaR)', 'The blueprint ME', 'The bid/ask spread'] },
    { q: 'The state of the system evolves by the transition rule…', answer: 3,
      options: ['x = constant', 'Y = f(X) only', 'x(t+1) = x(t)', 'x(t+1) = f(x(t), u(t), ε(t)) with decisions u and noise ε'] },
    { q: '"Deterministic" scenario building means…', answer: 0,
      options: ['A few hand-designed futures (optimistic / base / recession)', 'Millions of random draws', 'No assumptions at all', 'Sampling from a copula'],
      explain: 'Clear and easy to discuss, but it covers only a small part of the uncertainty space.' },
    { q: 'Stress testing applies a shift of the form…', answer: 2,
      options: ['x* × ε', 'x* / 2 always', 'x_stressed = x* + Δ (an extreme-but-plausible shock)', 'A random N(0,1) only'] },
    { q: 'Severe-but-plausible stress testing became a regulatory requirement mainly…', answer: 1,
      options: ['Before computers existed', 'After the 2008 crisis, because averages hide tail risk', 'To speed up trading', 'Only for mining'] },
    { q: 'In a scenario tree, the expected outcome is…', answer: 3,
      options: ['max over leaves', 'the first branch only', 'the median leaf', 'Σ P(sᵢ)·Yᵢ — probability-weighted over leaves'] },
    { q: 'Scenario trees are the backbone of…', answer: 0,
      options: ['Stochastic programming (ALM, energy, inventory)', 'Single-point forecasting', 'Linear regression', 'Bubble sort'] },
    { q: '"Counterfactual" scenarios are…', answer: 3,
      options: ['Endogenous decisions', 'Future forecasts', 'Random draws', 'Alternative what-ifs like "taxes 50% lower"'] },
    { q: 'Endogenous scenarios model…', answer: 1,
      options: ['External market shocks', 'Your own decisions (expansion, integration)', 'Tax legislation', 'The weather'] },
    { q: 'The key signal from a scenario is…', answer: 2,
      options: ['Its absolute profit only', 'The random seed', 'The change (delta) vs the baseline', 'The blueprint ME'] },
    { q: '"Viable" in the comparison means…', answer: 0,
      options: ['E[Profit] > 0 and P(loss) < 50%', 'Any profit at all', 'ROI above 100%', 'Zero risk'] },
    { q: 'A tornado chart shows…', answer: 3,
      options: ['Wind speed', 'The price path', 'The correlation matrix', 'Scenarios sorted by magnitude of profit impact'] },
    { q: 'The professional way to combine scenario and Monte-Carlo analysis is to…', answer: 1,
      options: ['Pick one and discard the other', 'Define macro scenarios, run Monte-Carlo inside each, then aggregate', 'Average two unrelated numbers', 'Replace both with a single forecast'] },
    { q: 'ML-assisted scenario generation typically uses…', answer: 2,
      options: ['Spreadsheets only', 'Bubble charts', 'VAEs, GANs and diffusion models to synthesise realistic market states', 'A single fixed scenario'] },
    { q: 'Reverse stress testing asks…', answer: 2,
      options: ['What is the median?', 'How many runs are needed?', 'What scenario would make the build unprofitable?', 'What is the average?'] },
  ],
}

const markowitz = {
  key: 'markowitz',
  title: 'Portfolio Allocation (Markowitz)',
  section: 'finance',
  sectionLabel: 'Quantitative Finance',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'Don’t pick the single best item — pick the mix that gives the most expected return for the risk you accept. Mean-variance optimisation, the efficient frontier, the covariance that powers diversification, and the water-filling solution behind the haul optimizer.',
  body: `# Portfolio Allocation (Markowitz)

**Mean-variance optimisation** chooses *how much* of your budget to put into each option so the
whole portfolio earns the most expected return for the amount of risk you are willing to carry.
Its key insight: the risk of a portfolio is **not** the average risk of its parts — combining
imperfectly-correlated assets cancels some risk for free.

> In one line: don't pick the single best item, pick the *mix* with the best return for your risk.

## From picking winners to building a portfolio

The naive move is to dump everything into the highest-return option. But a single position rises
*and falls* with one price. Spreading the budget across several positions whose prices don't move
in lockstep keeps the expected return while shrinking the swings. Markowitz turned that intuition
into math — and showed exactly how much to hold of each.

## A little history

**Harry Markowitz** published *"Portfolio Selection"* in 1952 (Journal of Finance) — the birth of
**Modern Portfolio Theory**. He was the first to treat risk quantitatively as the **variance** of
returns and to formalise diversification as a covariance effect. The work earned him the 1990 Nobel
Memorial Prize in Economics (shared with William Sharpe and Merton Miller).

## Two numbers per asset: return and risk

Describe each asset \`i\` by two moments: an **expected return** \`μᵢ = E[rᵢ]\` and a **risk**, the
standard deviation \`σᵢ\` (or variance \`σᵢ²\`). Choose **weights** \`wᵢ\` — the fraction of the
budget in each asset, with \`Σ wᵢ = 1\`. Then the portfolio has

- expected return \`r_p = Σ wᵢ·μᵢ\` — a simple weighted average (linear in the weights);
- variance \`σ_p² = Σᵢ Σⱼ wᵢ·wⱼ·σᵢⱼ = wᵀ·Σ·w\` — a **quadratic** form in the weights, where \`Σ\`
  is the **covariance matrix**.

The return is linear and boring; all the interesting behaviour lives in that quadratic variance.

## Covariance is where diversification lives

The off-diagonal entries are \`σᵢⱼ = ρᵢⱼ·σᵢ·σⱼ\`, with the **correlation** \`ρᵢⱼ\` between −1 and
+1. Mix two assets and the combined risk depends on \`ρ\`:

- \`ρ = +1\` (move together): no benefit — portfolio σ is the weighted average of the σ's.
- \`ρ < 1\`: the combined σ is **less** than that average — some risk cancels.
- \`ρ = −1\`: risk can cancel almost completely.

The lower the correlation, the more risk diversifies away. This is often called the only free lunch
in finance. When assets are **independent** (\`ρ = 0\`, a *diagonal* \`Σ\`) the variance collapses to
\`σ_p² = Σ wᵢ²·σᵢ²\`.

## The power of diversification

Take \`N\` independent assets with equal variance \`σ²\` and equal weights \`wᵢ = 1/N\`. The portfolio
variance becomes \`σ_p² = σ²/N\` — it shrinks like \`1/N\`. The asset-specific (**idiosyncratic**)
risk washes out; what's left is the **systematic** risk common to everything (a market-wide move),
which no amount of diversification removes.

[[fig:diversification|Adding more independent positions drives portfolio σ down like σ̄/√N, flattening at the systematic-risk floor that can't be diversified away.]]

## The efficient frontier

For every target return there is a portfolio with the **smallest possible variance**. Plot all of
them in *(risk, return)* space and you get a curve. Its upper edge is the **efficient frontier**:
for a given risk it gives the most return, and for a given return the least risk. Any portfolio
*below* the frontier is dominated — you can do strictly better. The leftmost point is the
**minimum-variance portfolio**, the safest mix you can build from these assets.

[[fig:efficientFrontier|Each blue dot is one asset; the green curve is the efficient frontier (best return per unit of risk). The white point is the minimum-variance portfolio; the amber point is a constrained, liquidity-capped choice that sits inside the frontier.]]

## The optimisation problem

Pick a point on the frontier by trading return against risk with a **risk-aversion** parameter
\`λ ≥ 0\`:

\`max_w  wᵀμ − (λ/2)·wᵀΣw\`   subject to   \`Σ wᵢ = 1\`   and (long-only)   \`wᵢ ≥ 0\`.

- \`λ → 0\` — chase return: concentrate on the highest-\`μ\` asset.
- \`λ → ∞\` — minimise variance: head for the minimum-variance portfolio.

Sweeping \`λ\` from small to large traces the **entire** efficient frontier. Mathematically this is
a **quadratic program** — a quadratic objective with linear constraints — solved via its
Lagrangian / **KKT** conditions. With the constraints dropped, the optimum is \`w ∝ Σ⁻¹μ\`, the
classic **two-fund (tangency)** result.

## Sharpe ratio and the tangency portfolio

If a **risk-free** asset paying \`r_f\` exists, the best risk-adjusted portfolio maximises the
**Sharpe ratio** \`(r_p − r_f)/σ_p\` — excess return per unit of risk. The straight line from
\`r_f\` tangent to the frontier is the **capital allocation line**, and its touch point is the
**tangency portfolio**.

> EVE has no real risk-free asset, so IndyOps drops \`r_f\` and steers purely with \`λ\`.

## Solving the diagonal case in closed form

When you ignore cross-correlations (a **diagonal** \`Σ\`), the KKT conditions collapse to a tidy
**water-filling** rule: \`wᵢ = max(0, (μᵢ − ν)/(λ·σᵢ²))\`. The single scalar \`ν\` is a *cutoff*
("water level") chosen so the weights sum to 1. Since \`Σ wᵢ(ν)\` only decreases as \`ν\` rises,
\`ν\` is found by **bisection**. Assets whose return sits below the cutoff get **zero** weight; the
rest get more the higher their return and the lower their variance.

[[fig:waterfill|Each bar is an asset's expected return μᵢ. Only the part above the cutoff ν is funded (green); the higher above the line and the lower its variance, the bigger the weight. Assets entirely below ν get nothing.]]

## Long-only and other constraints

The \`wᵢ ≥ 0\` constraint forbids **short-selling** — you can't hold a negative quantity of an EVE
item. Real plans add more: a **budget**, a **maximum weight** per asset, a minimum lot size. These
turn the clean closed form into a *bounded* problem solved numerically, but the spirit is the same.

## Limitations — handle with care

- **Estimation error.** \`μ\` and \`Σ\` are *estimated* from noisy history, and mean-variance is
  notoriously sensitive to them — tiny input changes swing the weights wildly ("error
  maximisation"). Shrinkage and constraints tame this.
- **Single period.** It optimises one horizon and ignores rebalancing over time.
- **Symmetric risk.** Variance penalises upside and downside equally and underweights fat tails;
  for tail risk reach for CVaR (see the Monte-Carlo article).
- **Ignores liquidity.** It assumes you can buy and sell the optimal amounts. Often you can't.

## In IndyOps

The **haul portfolio optimizer** (Market → Jita-C-J → Auto scanner) is mean-variance tuned for
trading reality:

- Each candidate's expected return \`μ\` is its per-unit **ROI**; its risk \`σ\` is the Jita price
  **coefficient of variation** from market history (floored, so a stable-priced arbitrage isn't
  treated as riskless and grabbed whole).
- The covariance is **diagonal**, so the native Fortran \`portfolio-opt\` engine solves it by the
  water-filling rule above — matched exactly by a Python oracle for parity.
- Then two caps make the plan **sellable**: a **liquidity cap** (\`participation · daily volume ·
  sell-through days\`) and a **diversification cap** (max share of budget per item). Because the
  real risk in hauling is *being unable to offload the position* — not day-to-day price wiggle —
  those caps, not \`σ\`, do most of the work.
- The report plots the **efficient frontier** with your chosen (liquidity-capped) portfolio marked
  *inside* it, plus the realised allocation weights.`,
  quiz: [
    { q: 'Mean-variance (Markowitz) optimisation trades off…', answer: 2,
      options: ['Blueprint ME vs TE', 'Buy price vs sell price', 'Expected return vs risk (variance)', 'Volume vs cargo'],
      explain: 'It maximises return for a chosen level of risk — the two moments μ and σ².' },
    { q: 'A portfolio’s expected return r_p equals…', answer: 0,
      options: ['Σ wᵢ·μᵢ — the weighted average of asset returns', 'The single highest μᵢ', 'wᵀΣw', 'max(μᵢ) − min(μᵢ)'],
      explain: 'Return is linear in the weights; variance is the quadratic part.' },
    { q: 'A portfolio’s variance σ_p² is…', answer: 3,
      options: ['Σ wᵢ·μᵢ', 'The average of the σᵢ', 'Always σ²/N', 'wᵀΣw — quadratic, depending on the covariances'],
      explain: 'σ_p² = ΣΣ wᵢwⱼσᵢⱼ = wᵀΣw; the covariances are what make diversification possible.' },
    { q: 'Diversification reduces risk the MOST when the assets are…', answer: 1,
      options: ['Perfectly positively correlated', 'Low- or negatively correlated', 'All identical', 'High variance'],
      explain: 'Low ρ means their moves partly cancel — the combined σ drops below the weighted average.' },
    { q: 'With covariance σᵢⱼ = ρᵢⱼ·σᵢ·σⱼ, if ρ = +1 between two assets…', answer: 2,
      options: ['Risk vanishes', 'Variance becomes negative', 'There is no diversification benefit', 'The return doubles'],
      explain: 'At ρ=1 the portfolio σ is just the weighted average of the σ’s — nothing cancels.' },
    { q: 'For N independent, equal-risk assets held in equal weights, σ_p² =…', answer: 1,
      options: ['σ²·N', 'σ²/N', 'σ²', 'N/σ²'],
      explain: 'Idiosyncratic risk averages away like 1/N as you add independent positions.' },
    { q: 'The risk that remains after diversifying across many assets is…', answer: 3,
      options: ['Idiosyncratic risk', 'Estimation error', 'Zero', 'Systematic (market-wide) risk'],
      explain: 'Diversification removes asset-specific risk; the common market component stays.' },
    { q: 'The efficient frontier is…', answer: 0,
      options: ['The set of portfolios with the most return for each level of risk', 'A single optimal portfolio', 'The list of all assets', 'The line of zero-risk portfolios'],
      explain: 'It is the upper-left boundary; portfolios below it are dominated.' },
    { q: 'The minimum-variance portfolio sits…', answer: 2,
      options: ['At the top-right of the frontier', 'Off the frontier', 'At the leftmost point of the frontier (lowest risk)', 'At ρ = 1'] },
    { q: 'In max wᵀμ − (λ/2)·wᵀΣw, increasing the risk-aversion λ makes the optimiser…', answer: 1,
      options: ['Chase the highest return', 'More risk-averse, toward the minimum-variance portfolio', 'Ignore the covariances', 'Short more assets'],
      explain: 'Large λ weights the −(λ/2)wᵀΣw risk term heavily.' },
    { q: 'As λ → 0 the optimiser tends to…', answer: 3,
      options: ['Equal-weight everything', 'Pick the minimum-variance portfolio', 'Fail to solve', 'Concentrate on the highest-return asset'],
      explain: 'With no risk penalty it just maximises wᵀμ.' },
    { q: 'Mathematically the Markowitz problem is a…', answer: 2,
      options: ['Linear program', 'Sorting problem', 'Quadratic program (quadratic objective, linear constraints)', 'Differential equation'] },
    { q: 'The Sharpe ratio is…', answer: 0,
      options: ['(r_p − r_f)/σ_p — excess return per unit of risk', 'r_p · σ_p', 'σ_p − r_p', 'The number of assets'],
      explain: 'It measures risk-adjusted return; the tangency portfolio maximises it.' },
    { q: 'For a diagonal Σ the weights are wᵢ = max(0,(μᵢ − ν)/(λ·σᵢ²)). The cutoff ν is chosen so…', answer: 1,
      options: ['Every asset gets equal weight', 'The weights sum to 1 (found by bisection)', 'Variance is zero', 'μ equals σ'],
      explain: 'Σ wᵢ(ν) decreases monotonically in ν, so a single bisection finds the level that normalises the weights.' },
    { q: 'In that water-filling solution, an asset whose return μᵢ is below the cutoff ν gets weight…', answer: 2,
      options: ['The largest weight', '1/N', 'Zero', 'A negative weight'],
      explain: 'max(0, …) clamps it out — only assets above the water level are funded.' },
    { q: 'The long-only constraint wᵢ ≥ 0 means…', answer: 1,
      options: ['You must hold every asset', 'No short-selling (you can’t hold negative quantities)', 'Weights can exceed 1', 'The budget is ignored'] },
    { q: 'A well-known weakness of mean-variance optimisation is that it is…', answer: 3,
      options: ['Too slow to compute', 'Unable to diversify', 'Only valid for two assets', 'Very sensitive to estimation error in μ and Σ'],
      explain: 'Small changes in the noisy inputs can swing the weights — sometimes called "error maximisation".' },
    { q: 'In the IndyOps haul optimizer, the dominant real risk handled by the caps (rather than by σ) is…', answer: 0,
      options: ['Liquidity — being unable to sell the volume you bought', 'Blueprint ME', 'Sales tax', 'Courier collateral'],
      explain: 'σ is price volatility; the binding constraint when hauling is offloading the position, so liquidity + diversification caps do most of the work.' },
  ],
}

export const ARTICLES = [monteCarlo, scenarios, markowitz]

// articles grouped by section (for the sidebar)
export const SECTIONS = ARTICLES.reduce((acc, a) => {
  const s = acc.find(x => x.section === a.section)
  if (s) s.articles.push(a)
  else acc.push({ section: a.section, label: a.sectionLabel, articles: [a] })
  return acc
}, [])
