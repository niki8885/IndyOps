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

const demand = {
  key: 'demand',
  title: 'Demand',
  section: 'demand',
  sectionLabel: 'Demand & Liquidity',
  level: 'Foundations',
  difficulty: 1,
  summary: 'What "demand" really means in a market — the willingness to buy at a price. EVE’s double-auction order book, where buy orders are standing demand; supply, the clearing price, the law of demand and elasticity; and why traded volume is only a proxy for the demand you actually want to know.',
  body: `# Demand

**Demand** is the quantity of a good buyers are *willing and able* to purchase at a given price.
It is not one number but a *relationship*: as the price falls, buyers want more; as it rises, they
want less. Everything downstream — what to produce, how much to stock, what it will sell for —
starts from understanding that relationship.

> In one line: demand is a *curve*, not a point — "how many units would clear at each price?"

## Demand is a schedule, not a quantity

Saying "demand for Tritanium is high" is loose. Precisely, demand is a **schedule**: at 5 ISK/unit
buyers want 2B units/day; at 6 ISK they want 1.4B; at 8 ISK only 600M. Plotted with price on the
vertical axis and quantity on the horizontal, this is the downward-sloping **demand curve**. The
**law of demand** says it slopes down: higher price → lower quantity demanded, all else equal.

[[fig:supplyDemand|Demand (green) slopes down, supply (red) slopes up. They cross at the market-clearing price and quantity — the only point where what buyers want equals what sellers offer.]]

## Supply, demand and the clearing price

A market price is not decreed; it is *discovered* where the two curves meet. **Supply** is the
mirror image — quantity sellers will offer at each price, sloping *up* (higher price draws out more
sellers). The crossing point is the **equilibrium** (market-clearing) price: the single price at
which the units buyers want exactly equals the units sellers offer. Above it there is a glut
(price falls); below it, a shortage (price rises).

When demand *shifts* — a new ship meta makes a hull popular — the whole curve moves right: more is
wanted at every price, so both the clearing price and the traded quantity rise. Distinguishing a
**movement along** the curve (a price change) from a **shift of** the curve (a demand change) is
the single most important idea here.

## EVE’s market is a continuous double auction

EVE does not match one buyer to one seller at a posted price. Its regional markets are a
**continuous double auction**: at any instant there is a book of resting **buy orders** (bids) and
**sell orders** (asks). A trade happens when an incoming order crosses the best resting order on the
other side.

[[fig:orderBook|The order book. Resting SELL orders (red) are standing supply above the spread; resting BUY orders (green) are standing demand below it. A trade fires when an order crosses the best price on the opposite side.]]

This makes one half of demand *directly observable*. The **buy orders sitting in the book are
standing demand**: real ISK committed to buy at stated prices. Their total volume is **bid depth**;
the highest is the **best bid**. The gap between best bid and best ask is the **bid-ask spread**,
and the midpoint is the **mid-price** — the market’s current fair-value estimate.

> Standing demand (resting buy orders) is what someone will pay *right now*. Flow demand (units
> actually traded per day) is what *did* change hands. They are related but not the same.

## Latent, derived and realised demand

- **Realised demand** — units that actually traded. This is what market **history** records as
  daily *volume*. It is the cleanest signal we get, but it is *censored*: if nothing was for sale,
  zero volume does not mean zero desire.
- **Standing demand** — resting buy orders right now (bid depth). Visible, but a snapshot.
- **Latent demand** — what buyers *would* take at a better price, never posted. Invisible.
- **Derived demand** — demand for an input because of demand for the output. Demand for minerals is
  *derived* from demand for the ships built from them; a hull boom pulls its whole bill of materials.

The quantity we truly care about — how much we could *sell per day* — is a blend we can only
*estimate* from realised volume and standing depth. That estimation problem is the whole point of
**demand metrics** and **demand forecasting**.

## Elasticity — how sharply demand reacts to price

**Price elasticity of demand** measures the *responsiveness* of quantity to price:
\`E = (%ΔQ) / (%ΔP)\`. If a 10% price rise cuts quantity by 20%, \`E = −2\` — **elastic**: buyers
flee. If it only cuts 3%, \`E = −0.3\` — **inelastic**: buyers stay. The sign is (almost) always
negative by the law of demand; we usually quote the magnitude.

[[fig:elasticity|Inelastic demand (amber, steep): quantity barely moves with price — fuel, ammo, necessities. Elastic demand (blue, flat): small price moves swing quantity hard — luxuries, substitutable goods.]]

Elasticity decides whether a price cut *raises* revenue. Where demand is elastic (\`|E| > 1\`),
dropping the price sells enough extra units to grow revenue; where it is inelastic (\`|E| < 1\`),
a price cut just leaves money on the table. In EVE, staples (fuel blocks, common ammo, minerals)
tend to be inelastic; faction toys and meta-chasing hulls are elastic and fad-driven.

## Demand and liquidity are different questions

High demand does not guarantee you can *transact*. **Liquidity** asks whether you can buy or sell
your size *quickly, near the mid-price, without moving it*. An item can have strong long-run demand
yet a thin book today (wide spread, shallow depth) — so a large sale still craters the price. Demand
tells you *whether* people want it; liquidity tells you *how cleanly you can act on that*. The two
travel together but must be measured separately — which is why this section has an article for each.

## In IndyOps

The **Market Browser** exposes demand from both sides. The **Orders** and **Order Book** tabs show
the live book — standing demand (bids), supply (asks), spread and depth. The **History** tab shows
realised demand as daily traded volume. The **Demand** tab distils these into the metrics covered in
the next article, and the **Prediction** tab forecasts where demand is heading. Throughout, remember
the core distinction: what you *see* (volume, bids) is a *proxy* for the latent demand you actually
want to plan against.`,
  quiz: [
    { q: 'In economics, "demand" is best described as…', answer: 2,
      options: ['A single quantity buyers want', 'The amount of stock for sale', 'A relationship (schedule) between price and quantity wanted', 'Today’s traded volume'],
      explain: 'Demand is a curve — quantity wanted at each price — not one number.' },
    { q: 'The law of demand says the demand curve…', answer: 1,
      options: ['Slopes upward', 'Slopes downward (higher price → lower quantity demanded)', 'Is flat', 'Is vertical'] },
    { q: 'The market-clearing (equilibrium) price is where…', answer: 3,
      options: ['Supply is zero', 'The spread is widest', 'Price is highest', 'The supply and demand curves cross (quantity wanted = quantity offered)'] },
    { q: 'EVE’s regional market is structured as a…', answer: 2,
      options: ['Single posted price', 'Sealed-bid auction once a day', 'Continuous double auction (a live book of bids and asks)', 'Dealer quote only'] },
    { q: 'In the order book, the resting BUY orders represent…', answer: 0,
      options: ['Standing demand (ISK committed to buy)', 'Supply', 'The sales tax', 'Realised volume'] },
    { q: 'The bid-ask spread is…', answer: 1,
      options: ['Total daily volume', 'The gap between the best bid and the best ask', 'The blueprint ME', 'The number of orders'] },
    { q: 'Daily traded "volume" in market history is an example of…', answer: 2,
      options: ['Latent demand', 'Standing demand', 'Realised demand (what actually changed hands)', 'Derived supply'] },
    { q: 'Why is realised volume only a PROXY for true demand?', answer: 3,
      options: ['It is always too high', 'It ignores the sell side', 'It is measured in ISK', 'It is censored — if nothing was for sale, zero volume ≠ zero desire'] },
    { q: 'Demand for minerals driven by demand for the ships built from them is called…', answer: 1,
      options: ['Latent demand', 'Derived demand', 'Elastic demand', 'Standing demand'] },
    { q: 'A movement ALONG the demand curve is caused by…', answer: 0,
      options: ['A change in the item’s own price', 'A new ship meta', 'A tax change', 'A change in incomes'],
      explain: 'A price change moves you along the curve; other factors SHIFT the whole curve.' },
    { q: 'Price elasticity of demand E = (%ΔQ)/(%ΔP). If E = −2, demand is…', answer: 2,
      options: ['Perfectly inelastic', 'Unit elastic', 'Elastic (quantity reacts strongly)', 'Upward sloping'] },
    { q: 'Cutting the price tends to RAISE revenue when demand is…', answer: 1,
      options: ['Inelastic (|E| < 1)', 'Elastic (|E| > 1)', 'Vertical', 'Zero'],
      explain: 'Elastic demand means the extra units sold more than offset the lower price.' },
    { q: 'Staples like fuel blocks and common ammo tend to be…', answer: 0,
      options: ['Inelastic (buyers keep buying despite price)', 'Perfectly elastic', 'Derived from luxuries', 'Free'] },
    { q: 'Liquidity differs from demand in that it asks…', answer: 3,
      options: ['Whether anyone wants the item', 'What the long-run price is', 'What the blueprint costs', 'Whether you can transact your size quickly near the mid without moving the price'] },
    { q: 'The mid-price is…', answer: 2,
      options: ['The best bid', 'The lowest ask', 'The midpoint between best bid and best ask', 'The all-time average'] },
  ],
}

const demandMetrics = {
  key: 'demand-metrics',
  title: 'Demand Metrics',
  section: 'demand',
  sectionLabel: 'Demand & Liquidity',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'Turn raw market history and the live order book into numbers that describe demand: throughput (ADV, ISK turnover), intermittency, trend and momentum, dispersion, order-book pressure, weekly seasonality, and a single composite demand score.',
  body: `# Demand Metrics

A price chart tells you what something *costs*; **demand metrics** tell you how much the market
actually *wants and moves*. They convert two raw inputs — the daily market **history** (date, price,
traded volume, order count) and the live **order book** — into a compact, comparable profile of
demand for any item.

> The goal: answer "how much can I move, how reliably, which way is it trending, and how
> contested is the book?" — in numbers you can rank items by.

## Throughput — how much actually moves

The backbone is **traded volume**: units that changed hands per day. From it:

- **Average Daily Volume (ADV)** over a window: \`ADV_k = mean(volume over the last k days)\`. We
  report **7-, 30- and 90-day** ADV — short windows react fast, long windows are stable.
- **Median daily volume** — the *typical* day, robust to one-off spikes a mean would inflate.
- **ISK turnover/day** — \`volume × price\`, the demand expressed in ISK rather than units. A million
  units of a cheap mineral and ten units of a faction module can mean very different businesses.

[[fig:advTrend|Daily traded volume (bars) with a 7-day moving average (white) that smooths the weekly wobble, and the fitted OLS trend (amber) showing the underlying direction.]]

## Intermittency — how often it trades at all

Many EVE items don’t trade every day. The **active-days ratio** = fraction of the last 90 days with
volume > 0. A ratio near 1 is a continuously liquid staple; a low ratio is **intermittent** demand
(sporadic, lumpy) and needs different forecasting (see Croston, next article). The average daily
**order count** is a companion liquidity/competition proxy: many active orders means a crowded,
contested book.

## Trend and momentum — which way demand is going

- **Trend slope** — fit a line to \`log(1 + volume)\` against time by ordinary least squares; the
  slope is the *relative* growth per day (e.g. +1%/day). Using log makes it a percentage trend and
  tames spikes.
- **Momentum** — \`ADV_7 / ADV_30\`. Above 1 means recent demand is running hotter than the month;
  below 1, cooling.
- **30-day change** — \`ADV_30 / ADV_prev30 − 1\`: this month’s throughput versus the previous month.

Together they separate a *level* (how much) from a *direction* (accelerating or fading) — a high but
falling item is a very different bet from a small but surging one.

## Dispersion — how steady the flow is

- **Volume CV** (coefficient of variation) = \`std(volume) / mean(volume)\` over the last 30 days. Low
  CV = a dependable river of demand; high CV = feast-or-famine you can’t plan around.
- **Spike z-score** = \`(today’s volume − mean₃₀) / std₃₀\`. How unusual today is — a z of +3 flags a
  demand event (patch, war, hype) worth a second look.

## Order-book pressure — demand right now

History is yesterday; the **live book** is now. From the aggregated book:

- **Bid depth / ask depth** — total units resting on the buy / sell side.
- **Order-book imbalance** = \`(bid_depth − ask_depth) / (bid_depth + ask_depth)\`, in [−1, +1].
  Positive = more standing demand than supply (buy pressure); negative = the reverse.
- **Demand-coverage days** = \`bid_depth / ADV_30\` — how many days of average demand are already
  sitting in buy orders. **Supply-coverage days** = \`ask_depth / ADV_30\` — how long the current
  sell stock would last. These translate raw depth into *time*, which is what actually matters.

## Seasonality — the weekly heartbeat

EVE demand has a strong **weekly** rhythm: weekends and EU/US primetime trade more. The **weekday
profile** is mean volume per day-of-week; the **weekend lift** is the weekend mean over the weekday
mean. The strength of that rhythm is measured by the **lag-7 autocorrelation** — the correlation of
the volume series with itself shifted by seven days. A high value says "last Tuesday predicts this
Tuesday", which the seasonal forecasting models exploit directly.

[[fig:weekdaySeason|Mean traded volume by weekday. The weekend bars (green) run higher than weekdays — a weekend lift the forecasting models pick up as period-7 seasonality.]]

## One number — the composite demand score

For screening, the individual metrics fold into a transparent **0–100 demand score**, a weighted
blend of three bounded components:

- **Liquidity** — a log-scaled ISK turnover/day (so a 100M-ISK item and a 100B-ISK item land on a
  comparable 0–1 scale).
- **Consistency** — the active-days ratio (does it trade reliably?).
- **Trend** — the trend slope squashed into 0–1 (is demand growing?).

\`score = 100 · (0.5·liquidity + 0.3·consistency + 0.2·trend)\`. It is a *heuristic* for ranking,
not a forecast — deliberately simple and explainable, with the weights visible.

[[fig:demandScore|The demand score as a weighted blend: liquidity (×0.5), consistency (×0.3) and trend (×0.2). Each component is bounded to 0–1, so the score is always a clean 0–100.]]

## Pitfalls

- **Units vs ISK.** Rank by *turnover*, not raw units, unless you specifically care about quantity.
- **Mean vs median on spiky items.** A single 100× day inflates the ADV; the median guards against it.
- **Zero ≠ no demand.** A low active-days ratio can mean nothing was *for sale*, not that nobody
  wanted it — censored demand (see the previous article).
- **The book is a snapshot.** Imbalance and coverage are point-in-time and can flip minute to minute.

## In IndyOps

The **Market → Demand** tab shows exactly these: an ADV/turnover stat grid, the daily-volume chart
with its 7-day MA and OLS trend, the weekday-seasonality bars, the live order-book pressure
(imbalance and coverage gauges), and the composite demand score with its component breakdown. All of
it is computed by the native Fortran **demand-engine** (a pure stdin→stdout numeric filter) with a
Python oracle as the parity-checked fallback — so the same numbers come out whether the binary is
present or not.`,
  quiz: [
    { q: 'The backbone input for demand metrics is…', answer: 2,
      options: ['The blueprint ME', 'The sales tax', 'Daily traded volume (units that changed hands)', 'The character’s wallet'] },
    { q: 'ADV_30 is…', answer: 1,
      options: ['The 30 highest volumes', 'The mean daily volume over the last 30 days', 'The 30-day price', 'The order count'] },
    { q: 'Why prefer the MEDIAN daily volume over the mean for some items?', answer: 3,
      options: ['It is faster to compute', 'It is always larger', 'It includes the spread', 'It is robust to one-off spikes a mean would inflate'] },
    { q: 'ISK turnover per day is computed as…', answer: 0,
      options: ['volume × price', 'volume / price', 'price − cost', 'bid − ask'],
      explain: 'It expresses demand in ISK, comparing a cheap-bulk item to an expensive-thin one fairly.' },
    { q: 'The active-days ratio measures…', answer: 2,
      options: ['Days since release', 'The price trend', 'The fraction of recent days with volume > 0 (intermittency)', 'The spread'] },
    { q: 'The trend slope is fitted on log(1+volume) mainly because…', answer: 1,
      options: ['Logs are faster', 'It makes the slope a relative (%) trend and tames spikes', 'Volume can be negative', 'It removes seasonality'] },
    { q: 'Momentum = ADV_7 / ADV_30 above 1 means…', answer: 0,
      options: ['Recent demand is running hotter than the monthly average', 'Demand is cooling', 'The item is illiquid', 'Price is falling'] },
    { q: 'Volume CV = std/mean over 30 days. A HIGH CV indicates…', answer: 3,
      options: ['Very steady demand', 'Negative demand', 'A pricing error', 'Feast-or-famine, hard-to-plan demand'] },
    { q: 'A volume spike z-score of +3 means…', answer: 1,
      options: ['Volume is exactly average', 'Today is unusually high vs the 30-day norm (a demand event)', 'The book is empty', 'The price tripled'] },
    { q: 'Order-book imbalance (bid_depth − ask_depth)/(bid_depth + ask_depth) > 0 means…', answer: 2,
      options: ['More supply than demand', 'The spread is zero', 'More standing demand than supply (buy pressure)', 'The item is delisted'] },
    { q: 'Demand-coverage days = bid_depth / ADV_30 expresses…', answer: 0,
      options: ['How many days of average demand are already resting in buy orders', 'The sales tax', 'The price volatility', 'The number of sell orders'] },
    { q: 'The weekend lift and lag-7 autocorrelation both capture…', answer: 1,
      options: ['Price trend', 'The weekly seasonality of demand', 'The bid-ask spread', 'Estimation error'] },
    { q: 'Lag-7 autocorrelation is the correlation of the volume series with…', answer: 3,
      options: ['Its mean', 'The price', 'A random series', 'Itself shifted by 7 days'] },
    { q: 'The composite demand score blends liquidity, consistency and trend. It is…', answer: 2,
      options: ['A precise forecast of next-week volume', 'The order count', 'A transparent heuristic for ranking, not a forecast', 'The bid-ask spread'] },
    { q: 'In the score 100·(0.5·liquidity + 0.3·consistency + 0.2·trend), liquidity uses…', answer: 1,
      options: ['Raw units, unscaled', 'Log-scaled ISK turnover/day (bounded to 0–1)', 'The blueprint cost', 'The spread'] },
    { q: 'The Demand tab’s metrics are computed by…', answer: 0,
      options: ['A native Fortran demand-engine with a parity-checked Python oracle fallback', 'A spreadsheet macro', 'The ESI server', 'A LaTeX renderer'] },
  ],
}

const demandForecasting = {
  key: 'demand-forecasting',
  title: 'Demand Forecasting',
  section: 'demand',
  sectionLabel: 'Demand & Liquidity',
  level: 'Advanced',
  difficulty: 3,
  summary: 'Predict future demand and price from history. Decomposition, naive and seasonal baselines, exponential smoothing (Holt-Winters), ARIMA/SARIMA, Croston for intermittent demand, prediction intervals, and how to honestly score a forecast with walk-forward backtesting and MASE.',
  body: `# Demand Forecasting

**Forecasting** turns a history of daily volume (and price) into a statement about the future: *how
much will sell, at roughly what price, with what uncertainty?* It is the difference between reacting
to the market and planning your production against it.

> A forecast without an honest error bar and a backtest is a guess in a suit. The bands and the
> score matter as much as the central line.

## A series is trend + seasonality + noise

Most demand series decompose into three parts: a slow **trend** (growing or fading), a repeating
**seasonal** pattern (EVE’s strong weekly rhythm), and irregular **noise**. Almost every model below
is a different way of estimating and projecting those components.

[[fig:decomposition|A daily series split into its parts: a slow trend, a repeating weekly seasonal wave, and the leftover residual noise. Models differ mainly in how they capture trend and seasonality.]]

## Baselines you must beat

Never trust a fancy model until it beats the dumb ones:

- **Naive** — tomorrow = today. Surprisingly hard to beat on a random walk (which prices nearly are).
- **Seasonal-naive** — next Tuesday = last Tuesday (\`ŷ(t+h) = y(t+h−7)\`). The benchmark for weekly
  demand, and the denominator of the MASE score below.
- **Moving average** — the mean of the last k days; smooths noise but lags trend and ignores season.

## Exponential smoothing — Holt and Holt-Winters

Exponential smoothing weights recent observations more, decaying geometrically.

- **Simple (SES)** — a smoothed level only: \`ℓ(t) = α·y(t) + (1−α)·ℓ(t−1)\`. Flat forecast.
- **Holt** — adds a **trend** component \`b(t)\`, so the forecast can slope.
- **Holt-Winters** — adds a **seasonal** component too: level + trend + a per-weekday seasonal
  index, each updated by its own smoothing rate (\`α, β, γ\`). This is the workhorse for series with
  a clear weekly cycle, and a strong default for EVE volume.

## ARIMA and SARIMA — modelling the autocorrelation

Where smoothing tracks level/trend/season directly, **ARIMA** models the *autocorrelation* — how
each day relates to recent days and recent shocks. Three letters:

- **AR(p)** — *autoregressive*: today is a regression on the last \`p\` days.
- **I(d)** — *integrated*: **difference** the series \`d\` times to make it **stationary** (remove
  trend). \`∇y(t) = y(t) − y(t−1)\`.
- **MA(q)** — *moving-average*: today depends on the last \`q\` random shocks (forecast errors).

**SARIMA** adds a *seasonal* triple \`(P, D, Q)\` at the season length \`s = 7\`, multiplying seasonal
AR/MA polynomials onto the non-seasonal ones — so it captures both "yesterday" and "last week". The
coefficients are fit by **Conditional Sum of Squares** (minimise the one-step prediction errors); a
**stationarity guard** rejects explosive parameter sets so multi-week forecasts don’t diverge, and
the order \`(p,d,q)(P,D,Q)\` is chosen by out-of-sample accuracy.

## Intermittent demand — Croston’s method

For items that trade in sporadic lumps (many zero days), averaging is wrong — it blends "nothing"
with "a lot" into a meaningless middle. **Croston’s method** separates the two: it smooths the
**size** of non-zero demands and the **interval** between them, then forecasts the *rate* =
size / interval. It is the right tool exactly when the active-days ratio is low.

## Confidence is not optional — prediction intervals

A point forecast is a line; the future is a cone. Each model also yields **prediction intervals** —
here **P10 / P50 / P90**: the median path plus the band you expect the truth to fall inside 80% of the
time. The band *widens* with the horizon because uncertainty compounds. A narrow band on a 7-day
forecast and a fat one at 90 days is honest; a flat band is a lie.

[[fig:fanChart|A fan chart: observed history (white), the P50 median forecast (amber dashed), and the P10–P90 band that fans out as the horizon — and the uncertainty — grows.]]

## Scoring a forecast honestly — walk-forward backtesting

You cannot judge a forecast on the data it was fit to. **Rolling-origin (walk-forward)** backtesting
mimics real use: train on data up to a cutoff, forecast the next \`h\` days, compare to what actually
happened, then roll the cutoff forward and repeat. Averaging the errors across folds gives an honest
out-of-sample estimate — and, per forecast step, the spread of those errors *is* the prediction band.

[[fig:walkForward|Walk-forward validation: the training window (blue) grows, the test window (amber) rolls forward fold by fold. Each test window is scored out-of-sample; the errors average into the metrics and feed the bands.]]

## Error metrics — and why MASE

- **MAE** — mean absolute error, in the series’ own units.
- **RMSE** — root-mean-square error; punishes big misses harder.
- **MAPE / sMAPE** — *percentage* errors; scale-free, but MAPE explodes near zero (bad for
  intermittent demand), which the symmetric **sMAPE** partly tames.
- **MASE** — **Mean Absolute Scaled Error**: MAE divided by the MAE of the **seasonal-naive**
  benchmark. **MASE < 1 means you beat naive; > 1 means you didn’t.** Because it is scaled and
  benchmark-relative, it compares fairly across items of wildly different volume — which is why it
  is the headline selection metric.

## Picking the winner — a model panel

No single model wins everywhere: smoothing shines on clean seasonal series, ARIMA on autocorrelated
ones, Croston on lumpy ones. So fit a **panel**, backtest each, and select the lowest-MASE model
*per item, per target*. The choice is data-driven, not dogmatic.

[[fig:modelPanel|Each candidate model scored by out-of-sample MASE. The seasonal-naive line sits at 1.0; bars left of it beat the benchmark. The lowest-MASE model (green) is selected for this series.]]

## From forecast to decision

A forecast is only useful if it changes an action. Combining the projected **volume** and **price**
gives an expected **ISK turnover/day**, and comparing the forecast against recent demand yields a
simple **produce / hold / avoid** signal: rising sellable volume at a stable-or-rising price says
*produce*; collapsing demand says *avoid*.

## Limitations

- **Regime change.** Patches, wars and meta shifts break the past–future link no statistical model
  can foresee — bands help, but exogenous shocks dominate.
- **Short history.** ESI gives ~13 months of daily candles; deep seasonality beyond that is invisible.
- **Garbage in.** Censored zero-volume days and thin books distort every model; clean and flag first.

## In IndyOps

The **Market → Prediction** tab forecasts volume *and* price at 7 / 30 / 90 days. It runs the full
panel — seasonal-naive, Holt, Holt-Winters, Croston, ARIMA and **SARIMA** — walk-forward backtests
each, and shows the chosen model, the P10–P90 fan charts, the MASE/MAPE/sMAPE table, the candidate
ranking and the produce/hold/avoid signal. All of it is the native Fortran **forecast-engine**
(SARIMA estimated by CSS + a hand-rolled optimiser, no external libraries), with a pure-Python oracle
as the parity-checked fallback; a worker precomputes the liquid universe so the tab loads instantly.`,
  quiz: [
    { q: 'A demand time series is commonly decomposed into…', answer: 2,
      options: ['Bid, ask and spread', 'Mean, median and mode', 'Trend, seasonality and noise', 'AR, MA and tax'] },
    { q: 'The seasonal-naive forecast for daily EVE volume sets next Tuesday equal to…', answer: 1,
      options: ['The 30-day mean', 'Last Tuesday (y at t−7)', 'Zero', 'Yesterday'] },
    { q: 'Holt-Winters extends exponential smoothing by adding…', answer: 3,
      options: ['A tax term', 'Nothing — it is just SES', 'Only a trend', 'Both a trend and a seasonal component'] },
    { q: 'In ARIMA, the "I" (integrated, order d) refers to…', answer: 0,
      options: ['Differencing the series d times to make it stationary', 'Integrating profit', 'Adding interest', 'The seasonal period'] },
    { q: 'The AR(p) part of ARIMA models today as…', answer: 2,
      options: ['A constant', 'Last week only', 'A regression on the previous p observations', 'Pure noise'] },
    { q: 'The MA(q) part models today as depending on…', answer: 1,
      options: ['The price', 'The last q random shocks (past forecast errors)', 'The bid-ask spread', 'The blueprint'] },
    { q: 'SARIMA differs from ARIMA by adding…', answer: 3,
      options: ['A tax adjustment', 'A risk-free rate', 'Monte-Carlo sampling', 'A seasonal (P,D,Q) component at period s (here 7)'] },
    { q: 'SARIMA coefficients here are fit by Conditional Sum of Squares, which minimises…', answer: 0,
      options: ['The one-step prediction errors', 'The bid-ask spread', 'The number of parameters', 'The trading tax'] },
    { q: 'The stationarity guard exists to…', answer: 2,
      options: ['Speed up the fit', 'Add seasonality', 'Reject explosive parameters so multi-week forecasts don’t diverge', 'Remove the trend'] },
    { q: 'Croston’s method is the right choice when demand is…', answer: 1,
      options: ['Perfectly seasonal', 'Intermittent (many zero days, sporadic lumps)', 'A smooth uptrend', 'Constant'] },
    { q: 'Prediction intervals (P10/P50/P90) should, as the horizon grows…', answer: 3,
      options: ['Stay flat', 'Shrink to zero', 'Become a single line', 'Widen, because uncertainty compounds'] },
    { q: 'Walk-forward (rolling-origin) backtesting is needed because…', answer: 0,
      options: ['You can’t judge a forecast on the data it was fit to — you need out-of-sample errors', 'It is faster', 'It removes seasonality', 'It guarantees profit'] },
    { q: 'MASE compares a model’s error to…', answer: 2,
      options: ['Zero', 'The RMSE', 'The seasonal-naive benchmark (MASE < 1 beats naive)', 'The price'] },
    { q: 'Why is MAPE a poor metric for intermittent demand?', answer: 1,
      options: ['It ignores the trend', 'It explodes when actual values are near zero', 'It is not scale-free', 'It needs the order book'] },
    { q: 'Why fit a PANEL of models and select per item?', answer: 3,
      options: ['To use more CPU', 'Because more models are always better', 'To avoid backtesting', 'Because no single model wins everywhere — the best depends on the series'] },
    { q: 'A practical limit of statistical demand forecasting is…', answer: 0,
      options: ['Regime changes (patches, wars, meta shifts) the past can’t foresee', 'It cannot add two numbers', 'It needs no data', 'It always beats naive'] },
    { q: 'In IndyOps, the Prediction tab’s heavy compute runs on…', answer: 2,
      options: ['The ESI server', 'A spreadsheet', 'A native Fortran forecast-engine with a parity-checked Python oracle', 'The web browser only'] },
  ],
}

const liquidityRisk = {
  key: 'liquidity-risk',
  title: 'Liquidity Risk',
  section: 'demand',
  sectionLabel: 'Demand & Liquidity',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'The risk that you can’t trade your size quickly near the fair price. Spread, depth and resiliency; slippage and the square-root market-impact law; days-to-liquidate and participation; how liquidity differs from volatility, and why it — not price wiggle — is the binding constraint when hauling.',
  body: `# Liquidity Risk

**Liquidity** is the ease of converting a position to ISK (or back) *quickly, in size, and near the
fair price*. **Liquidity risk** is the danger that you cannot — that selling your stock forces the
price down, or that there simply aren’t enough buyers before you need the ISK. It is the risk that
hides behind a healthy-looking price chart and ruins otherwise-profitable plans.

> Price risk asks "will the value move against me?" Liquidity risk asks "can I even get out at that
> value, in my size, when I need to?"

## Three dimensions of liquidity

A market’s liquidity has three distinct faces:

- **Tightness** — the **bid-ask spread**: the round-trip cost of trading immediately. Tight is liquid.
- **Depth** — how many units rest near the best price; can the book absorb a big order without the
  price walking far?
- **Resiliency** — how fast the book *refills* after a large trade eats through it.

An item can be tight but shallow (fine for small trades, brutal for big ones), or deep but slow to
refill. All three matter.

## The bid-ask spread and market depth

The **spread** is the immediate, guaranteed cost of liquidity: buy at the ask, sell at the bid, and
you start down by the spread before the price moves at all. **Depth** is the cushion behind each
side — the cumulative volume stacked at successive price levels.

[[fig:spreadDepth|The order book’s cumulative depth on both sides. The shaded gap is the bid-ask spread (tightness); the height of each curve is depth — how much size the book can absorb before the price walks.]]

## Slippage and market impact

Real fills happen *across* the book, not at a single price. A buy order large enough to clear the
best ask keeps climbing to the next, and the next — so your **average execution price** is worse than
the quote you saw. That gap is **slippage**, and the act of pushing the price by trading is **market
impact**.

Impact grows **sub-linearly** with size — empirically close to a **square-root law**:
\`impact ≈ k · σ · √(Q / V)\`, where \`Q\` is your order size, \`V\` is daily volume and \`σ\` is
volatility. Doubling your size more than doubles… no — it grows like √, so trading *patiently in
slices* (a smaller share of volume per unit time) is how professionals cut impact.

[[fig:marketImpact|As order size grows relative to book depth, the average execution price walks away from the best quote. The slippage curve follows a roughly square-root market-impact law.]]

## The time–size trade-off: days-to-liquidate

You can always sell fast *or* sell well, rarely both. The key planning number is **days-to-liquidate**
= \`position / (participation · ADV)\`: at a sustainable **participation rate** (the share of daily
volume you can be without becoming the market — often 10–20%), how many days to unwind? A position
that takes 40 days to clear is exposed to 40 days of price risk *and* anything that kills demand
meanwhile. **Coverage days** (from the demand metrics) is the same idea read off the book.

## Measuring illiquidity

- **Quoted spread** (and spread as % of mid) — the cheapest, most direct gauge.
- **Turnover / ADV** — how much trades relative to what’s outstanding; low turnover = illiquid.
- **Amihud illiquidity** — \`mean(|return| / ISK volume)\`: how much the price moves per ISK traded.
  A high value means small trades shove the price — the essence of illiquidity in one number.
- **Days-to-liquidate / participation** — the time dimension above.

## Liquidity risk is NOT volatility risk

This is the central confusion to avoid. **Volatility** (σ) measures how much the price *wiggles*.
**Liquidity** measures whether you can *act* at that price in your size. They are different axes:

[[fig:liqVsVol|Two independent risks. Liquid-and-calm items (green) are safe to size up; illiquid-and-volatile items (red) are dangerous even when the average looks fine. A portfolio σ alone misses the horizontal axis entirely.]]

A mean-variance optimiser that only sees σ will happily pour the budget into a high-return, low-σ
item — and then you discover the book is three orders deep and your position can’t be sold. The
volatility was low; the *liquidity* risk was lethal. This is exactly why a pure Markowitz weight
(see the Portfolio article) must be **capped** by liquidity.

## Liquidity in a portfolio — the binding constraint

For a trader moving real volume, liquidity — not day-to-day price σ — is usually the binding
constraint. Two caps make a plan *executable*:

- **Liquidity cap** — never allocate more than \`participation · ADV · sell-through_days\` of any
  item, so the position can actually be offloaded in a reasonable time.
- **Diversification cap** — a maximum share of budget per item, so a single thin market can’t sink
  the book.

These caps, more than the covariance matrix, do the real risk work in a hauling/trading plan.

## Liquidity spirals and crises

Liquidity is **state-dependent**: it evaporates exactly when you need it. In a sell-off everyone
heads for the exit at once, spreads blow out, depth vanishes, and forced sales push prices down —
which triggers more forced sales: a **liquidity spiral**. EVE has its own versions — a nerf, a war,
or a market-seeding cartel pulling orders can hollow a book overnight. The lesson: size positions for
the *bad* day’s liquidity, not the calm day’s.

## In IndyOps

Liquidity shows up across the toolset. The **Market → Order Book** and **Demand** tabs expose spread,
depth, imbalance and **coverage days** directly. The **haul portfolio optimizer** is mean-variance
*with* a liquidity cap (participation × daily volume × sell-through) and a diversification cap — the
article on Portfolio Allocation explains why those caps, not σ, carry the load. And the Monte-Carlo
profit simulator models a **liquidity/fill** term, so a thin product’s build reads as the slow,
risky unwind it really is rather than an instant sale.`,
  quiz: [
    { q: 'Liquidity risk is the risk that…', answer: 2,
      options: ['The price will rise', 'A blueprint is missing', 'You can’t trade your size quickly near the fair price', 'Taxes increase'] },
    { q: 'The three dimensions of liquidity are…', answer: 1,
      options: ['Mean, variance, skew', 'Tightness (spread), depth, and resiliency', 'Trend, season, noise', 'Bid, ask, mid'] },
    { q: 'The bid-ask spread represents…', answer: 0,
      options: ['The immediate round-trip cost of trading now (tightness)', 'The daily volume', 'The blueprint ME', 'The sales tax only'] },
    { q: 'Depth refers to…', answer: 3,
      options: ['How volatile the price is', 'The spread width', 'The number of items in the game', 'How much volume rests near the best price to absorb large orders'] },
    { q: 'Slippage is…', answer: 1,
      options: ['A type of tax', 'The gap between your average execution price and the quoted best price', 'The blueprint research time', 'The mid-price'] },
    { q: 'Market impact grows with order size approximately like…', answer: 2,
      options: ['Linearly', 'Exponentially', 'A square-root law (sub-linear)', 'Not at all'],
      explain: 'impact ≈ k·σ·√(Q/V) — which is why slicing orders over time reduces it.' },
    { q: 'The professional way to reduce market impact is to…', answer: 0,
      options: ['Trade patiently in slices (a smaller share of volume over time)', 'Send one huge market order', 'Raise the price', 'Ignore depth'] },
    { q: 'Days-to-liquidate = position / (participation · ADV) tells you…', answer: 3,
      options: ['The tax owed', 'The blueprint ME', 'The bid-ask spread', 'How long it takes to unwind a position at a sustainable share of volume'] },
    { q: 'A sensible participation rate (share of daily volume you trade) is typically…', answer: 1,
      options: ['100%+', 'Around 10–20%', 'Exactly 1 unit', '0%'] },
    { q: 'Amihud illiquidity, mean(|return| / ISK volume), is high when…', answer: 2,
      options: ['The spread is zero', 'Volume is enormous', 'Small trades move the price a lot (very illiquid)', 'The item is risk-free'] },
    { q: 'The key distinction between liquidity risk and volatility risk is…', answer: 0,
      options: ['σ measures price wiggle; liquidity measures whether you can act at that price in size', 'They are identical', 'Volatility is always larger', 'Liquidity only matters for blueprints'] },
    { q: 'A low-σ item can still be dangerous because…', answer: 3,
      options: ['Taxes are high', 'It has a high ME', 'The price never moves', 'It may be illiquid — a thin book you can’t exit in size'] },
    { q: 'Why must a pure Markowitz (mean-variance) weight be capped by liquidity?', answer: 1,
      options: ['To pay less tax', 'Because the optimiser sees only σ and will overload an item the market can’t actually absorb', 'To remove diversification', 'To increase the spread'] },
    { q: 'In the haul optimizer, the dominant risk handled by the caps (not by σ) is…', answer: 2,
      options: ['Courier collateral', 'Blueprint invention', 'Liquidity — being unable to offload the volume bought', 'Sales tax'] },
    { q: 'A "liquidity spiral" is dangerous because liquidity…', answer: 0,
      options: ['Evaporates exactly when you need it (forced sales beget forced sales)', 'Is always constant', 'Only improves in a crisis', 'Has no effect on price'] },
    { q: 'The practical lesson of state-dependent liquidity is to size positions for…', answer: 1,
      options: ['The calmest possible day', 'The bad day’s liquidity, not the calm day’s', 'Zero risk', 'Maximum leverage'] },
  ],
}

const orderBookMicrostructure = {
  key: 'order-book-microstructure',
  title: 'Order Book Microstructure',
  section: 'demand',
  sectionLabel: 'Demand & Liquidity',
  level: 'Advanced',
  difficulty: 3,
  summary: 'The machinery underneath the price: the limit order book, makers vs takers, price-time priority, why the bid-ask spread exists (order processing, inventory, adverse selection), order-book imbalance and the microprice, market impact — and EVE’s own quirks: order range, the 5-minute cooldown and the 0.01 ISK undercut war.',
  body: `# Order Book Microstructure

Where the **Demand** article draws supply and demand as smooth curves, **market microstructure**
studies the actual *machinery* that produces a price: individual orders, the book they rest in, the
rule that matches them, and the costs and incentives of the traders on each side. It is the
close-up view — the gears behind the clean macro picture.

> Microstructure asks the granular questions: *who posts, who takes, who fills first, why does the
> spread exist, and what does the shape of the book tell you about the next tick?*

## The limit order book

Two order types build everything:

- A **limit order** says *"buy/sell up to N units, but no worse than price P"*. If it can’t fill
  immediately it **rests** in the book as visible liquidity. In EVE these are your **buy orders**
  and **sell orders**.
- A **market order** says *"fill N units now, at whatever price"*. It **takes** resting liquidity,
  walking up or down the book until filled. EVE has no pure market order — you place an immediate
  order that crosses the best resting price, which is the same act.

The **limit order book (LOB)** is the sorted collection of all resting limit orders: bids (buy)
descending from the best, asks (sell) ascending from the best.

[[fig:orderBook|The limit order book: resting sell orders (red) stacked above the spread, resting buy orders (green) below. A taker’s order crosses the best price on the opposite side to trade.]]

## Makers and takers

Every fill has two roles. The **maker** posted the resting order and *provided* liquidity; the
**taker** crossed the spread and *consumed* it. The choice is patience vs immediacy:

- **Be a maker** (post a buy/sell order): you wait, you risk being undercut or never filling, but you
  capture the spread and avoid paying it.
- **Be a taker** (cross the spread now): you get certainty and speed, but you *pay* the spread and any
  slippage.

Real exchanges pay makers and charge takers (the *maker-taker* model) precisely to reward liquidity
provision. EVE’s analogue is the **broker fee** on placing an order plus the **sales tax** on selling
— the cost of doing business that the spread must cover.

## Price-time priority — who fills first

When a taker arrives, which resting order fills? The matching rule is **price-time priority**:

1. **Price priority** — the best price fills first (highest bid for an incoming sell, lowest ask for
   an incoming buy).
2. **Time priority** — *within* a price level, the order that arrived **first** fills first (FIFO).

So your **queue position** matters: post at the best price and you still wait behind everyone already
there. This is exactly why traders race to improve the price by a hair — jumping the queue.

[[fig:priceTimePriority|Price-time priority: better prices fill before worse ones (price priority, vertical), and within a level the earliest order fills first (time priority / FIFO, horizontal). Your queue position is your place in line.]]

## Why does the spread exist? Three costs

The **bid-ask spread** is not arbitrary greed; it compensates a liquidity provider for three real
costs (the classic decomposition):

- **Order-processing cost** — the mechanical cost of quoting and transacting (fees, effort, capital).
- **Inventory-holding cost** — a maker who gets filled now holds an unwanted position and bears its
  price risk until it can be offloaded; the spread pays for that risk.
- **Adverse-selection cost** — the maker quotes to *everyone*, including better-informed traders. If
  someone knows the price is about to rise, they lift the maker’s ask; the maker systematically
  trades against information and loses. The spread is the toll that covers those losses.

[[fig:spreadDecomp|The bid-ask spread decomposed: order-processing, inventory-holding and adverse-selection costs. Adverse selection — trading against the informed — is usually the largest and the reason spreads widen on news.]]

## Adverse selection and informed trading

The adverse-selection idea is the heart of modern microstructure. In the **Glosten-Milgrom** model,
a market maker who can’t tell informed from noise traders must set a spread wide enough that gains
from the uninformed cover losses to the informed. The more information asymmetry, the wider the
spread.

**Kyle’s λ** (lambda) makes the *impact* side precise: price moves linearly with net order flow,
\`ΔP = λ · (order flow)\`, where **λ measures illiquidity** — how much a unit of net buying or
selling shoves the price. A deep, liquid book has small λ; a thin one has large λ. λ is, in effect,
the slope of the market-impact curve.

## Depth, resiliency and the shape of the book

Beyond the best quote, **depth** is the volume resting at successive levels, and **resiliency** is
how fast the book refills after a trade eats through it. The *shape* matters: a book that is thick
right at the touch but hollow behind it looks liquid until you trade size, then isn’t.

[[fig:spreadDepth|Cumulative depth on both sides of the book. The gap is the spread (tightness); the height is depth (how much size absorbs before the price walks). A thin book behind a tight quote is a trap for large orders.]]

## Order-book imbalance and the microprice

The book is *predictive* at short horizons. **Order-book imbalance**
\`I = (Q_bid − Q_ask) / (Q_bid + Q_ask)\` (in [−1, +1]) leans positive when buyers crowd the book —
which tends to precede an up-tick. The **microprice** refines the mid by weighting each side by the
*opposite* side’s size:

\`p_micro = (P_ask·Q_bid + P_bid·Q_ask) / (Q_bid + Q_ask)\`.

When the bid is deep and the ask is thin, the microprice sits *above* the mid — the book is telling
you the next move is likely up. It is a better short-term fair-value estimate than the naive mid.

[[fig:microprice|With a deep bid and a thin ask (positive imbalance), the microprice leans toward the ask, above the simple mid — a short-horizon signal that price is more likely to rise than fall.]]

## Order flow and market impact

A taker who buys pushes the price up by consuming asks — part of that move is **temporary** (the book
refills, price reverts) and part is **permanent** (the trade revealed information, the level resets
higher). Splitting a big order into slices and trading patiently keeps you a small share of order
flow, minimising the permanent footprint — the micro-level reason the **square-root impact law** (see
*Liquidity Risk*) holds.

## EVE’s microstructure — its own beast

EVE is a limit-order market, but with rules that make its microstructure distinctive:

- **Regional, not global.** Each region has its own book; an order has a **range** (station-only up to
  region-wide) governing which buy orders a sell can match. **Min volume** lets a buy order demand a
  minimum lot.
- **Slow by design.** Orders modify on a **~5-minute cooldown** and the server ticks in seconds —
  there is **no sub-second HFT/latency game**. Microstructure here is a game of patience and fees, not
  nanoseconds.
- **Fees shape behaviour.** A **broker fee** is charged to *place* an order and again to *modify/relist*
  it; **sales tax** hits each sale. These costs set the economic floor of the next point.
- **The 0.01 ISK undercut war.** To win price priority you only need to beat the best by the smallest
  tick. So competitors repeatedly **undercut by 0.01 ISK**, each relist nudging the best ask down —
  until the price grinds to the **cost-plus-fee floor**, where further undercutting loses money. Then
  orders expire or someone relists higher and it resets.

[[fig:undercutWar|The 0.01 ISK undercut war: the best ask is ground down by repeated tiny undercuts toward the cost-plus-fee floor, then reset by relists. Broker/relist fees are what stop it falling below the floor.]]

> The undercut war is microstructure in miniature: price-time priority (beat the best to jump the
> queue) plus relist fees (a real cost) produce an equilibrium price pinned just above cost — exactly
> the competitive outcome theory predicts, played out 0.01 ISK at a time.

## What the book does NOT show

- **Latent demand** — orders never posted (the buyer waiting for a better price) are invisible.
- **Icebergs / hidden size** — less of an issue in EVE, but a reminder the visible book ≠ all interest.
- **It is a snapshot.** Imbalance and microprice can flip in minutes; treat them as short-horizon
  signals, not steady state.

## In IndyOps

The **Market → Order Book** tab is a direct microstructure view: it pulls the raw ESI orders for a
(region, item) and aggregates them into a **price-level depth ladder** plus a cumulative **market-depth
chart** — best bid/ask, spread, mid, and bid/ask depth. The **Demand** tab adds the **order-book
imbalance** and **coverage-days** metrics built on that same aggregation, and the **Orders** tab lists
the individual resting orders with their range, min-volume and expiry. Together they let you read the
machinery — queue, spread, depth, pressure — behind any item’s price.`,
  quiz: [
    { q: 'Market microstructure is the study of…', answer: 2,
      options: ['Long-run supply curves only', 'Blueprint research', 'The actual mechanism of trading and price formation (orders, the book, matching)', 'Tax policy'] },
    { q: 'A limit order…', answer: 1,
      options: ['Always fills immediately at any price', 'Rests in the book as liquidity until it can fill at its price or better', 'Is the same as a market order', 'Cannot be cancelled'] },
    { q: 'In the maker/taker distinction, the MAKER…', answer: 0,
      options: ['Posts a resting order and provides liquidity (captures the spread)', 'Crosses the spread and consumes liquidity', 'Pays the highest fee always', 'Is the exchange itself'] },
    { q: 'The matching rule "price-time priority" means…', answer: 3,
      options: ['Random fills', 'Largest order fills first', 'Newest order fills first', 'Best price fills first; within a price, earliest (FIFO) fills first'] },
    { q: 'Why does your queue POSITION matter?', answer: 1,
      options: ['It changes the tax', 'At the same price, earlier orders fill before yours (time priority)', 'It sets the blueprint ME', 'It widens the spread'] },
    { q: 'The bid-ask spread compensates the liquidity provider for three costs:', answer: 2,
      options: ['Tax, shipping, insurance', 'Trend, season, noise', 'Order-processing, inventory-holding, adverse-selection', 'AR, MA, differencing'] },
    { q: 'Adverse-selection cost arises because the maker…', answer: 0,
      options: ['Trades against better-informed traders and systematically loses to them', 'Pays too much tax', 'Holds no inventory', 'Never gets filled'] },
    { q: 'In the Glosten-Milgrom view, the spread WIDENS when…', answer: 3,
      options: ['Volume rises', 'Fees fall', 'The book is deep', 'Information asymmetry grows (more informed trading)'] },
    { q: 'Kyle’s λ in ΔP = λ·(order flow) measures…', answer: 1,
      options: ['The tax rate', 'Illiquidity — how much net order flow moves the price', 'The seasonal period', 'The blueprint ME'] },
    { q: 'Order-book imbalance I = (Q_bid − Q_ask)/(Q_bid + Q_ask) being positive suggests…', answer: 2,
      options: ['Price likely to fall', 'The item is delisted', 'Buy pressure — price more likely to tick up at short horizon', 'Zero volatility'] },
    { q: 'The microprice (P_ask·Q_bid + P_bid·Q_ask)/(Q_bid+Q_ask) improves on the mid by…', answer: 0,
      options: ['Weighting each side by the opposite side’s size, so it leans toward the heavier book', 'Ignoring depth', 'Using only the best ask', 'Averaging the day’s trades'] },
    { q: 'Splitting a large order into slices reduces…', answer: 1,
      options: ['The sales tax', 'Market impact (your share of order flow, hence the permanent price footprint)', 'The blueprint cost', 'The seasonal pattern'] },
    { q: 'A key way EVE’s microstructure differs from real HFT markets is…', answer: 3,
      options: ['It has no orders', 'It has no spread', 'Prices never change', 'No sub-second latency game — a ~5-minute modify cooldown and second-scale ticks'] },
    { q: 'The 0.01 ISK undercut war happens because…', answer: 2,
      options: ['Taxes are zero', 'Orders never expire', 'You only need to beat the best price by the smallest tick to win price priority', 'The book is hidden'] },
    { q: 'What stops the undercut war from driving the price arbitrarily low?', answer: 0,
      options: ['Broker/relist fees and cost — undercutting below the cost-plus-fee floor loses money', 'A price cap by CCP', 'The blueprint ME', 'Nothing — it goes to zero'] },
    { q: 'A limitation of reading the order book is that it does NOT show…', answer: 1,
      options: ['The best bid', 'Latent demand — interest from buyers who never posted an order', 'The spread', 'The depth'] },
    { q: 'In IndyOps, the Order Book tab builds its depth ladder by…', answer: 2,
      options: ['Forecasting with SARIMA', 'Reading the blueprint', 'Aggregating raw ESI orders for a (region, item) into price levels with cumulative depth', 'Querying the sales tax'] },
  ],
}

const supply = {
  key: 'supply',
  title: 'Supply',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Foundations',
  difficulty: 1,
  summary: 'The mirror of demand: how much sellers will offer at each price. The supply curve and the law of supply, marginal cost as the supply curve, what shifts supply vs moves along it, producer surplus, and short- vs long-run supply in EVE.',
  body: `# Supply

**Supply** is the quantity of a good sellers are *willing and able* to offer at each price. Like
demand, it is a *relationship*, not a number — and it is the other blade of the scissors that cuts
out a market price. Where demand comes from buyers’ willingness to pay, supply comes from producers’
**costs**.

> In one line: supply answers "how many units would sellers bring to market at each price?" — and the
> answer is governed by what it costs them to make one more.

## The law of supply

Plot price (vertical) against quantity offered (horizontal) and the **supply curve** slopes *up*:
higher prices coax out more units. The **law of supply** is this positive relationship. Why up? Because
making more usually costs more at the margin — so a higher price is needed to make the next, costlier
unit worth producing.

[[fig:supplyCurve|The supply curve slopes up because it traces marginal cost. The shaded triangle between the price and the curve is producer surplus — the gain to sellers who would have sold for less.]]

## The supply curve *is* the marginal-cost curve

This is the key idea. A profit-seeking seller offers one more unit whenever its price covers the
**marginal cost** of making it. So the supply curve is essentially the **marginal-cost (MC) curve**:
at price P, sellers supply every unit whose MC is below P. (More precisely, in competitive markets the
short-run supply curve is the MC curve above average variable cost — below that, it’s better to stop.)
This is why "supply" and "cost structure" are two views of the same thing — see the *Cost Structures*
article.

## Movements vs shifts — the crucial distinction

- A **movement along** the supply curve is caused by the good’s **own price** changing — more is
  supplied simply because it pays better.
- A **shift of** the whole curve is caused by something *else*: input costs, technology, taxes, the
  number of sellers. Cheaper inputs or better tech shift supply **right** (more at every price);
  a new tax or costlier inputs shift it **left**.

[[fig:supplyShift|A rightward shift (lower cost or better tech) means more is supplied at every price — distinct from a movement along a fixed curve caused only by the item’s own price.]]

Confusing the two is the classic error: a price rise is a *movement*; a cost change is a *shift*.

## Producer surplus

Not every seller needs the market price to sell — some would happily sell for less. The gap between
the price they receive and the lowest price they’d accept (their marginal cost) is **producer
surplus**: the seller’s gain from trade, the area *above* the supply curve and *below* the price, up to
the quantity sold. It is the mirror of consumer surplus (see *Consumer & Producer Surplus*).

## Elasticity of supply

Just as demand has elasticity, so does supply: \`E_s = (%ΔQ_supplied) / (%ΔP)\`. Supply is **elastic**
when producers can ramp output quickly (spare capacity, fast production), **inelastic** when they
can’t (fixed capacity, long build times). In EVE, an item with idle factory slots and stockpiled
minerals has elastic supply; one bottlenecked on a rare input or a long manufacturing timer is
inelastic — its price spikes when demand jumps because output can’t respond fast.

## Short run vs long run

- **Short run** — some inputs are fixed (you can’t conjure more factory slots or build time
  instantly), so supply is less elastic and prices can run high.
- **Long run** — sellers enter, capacity expands, and supply becomes far more elastic. In a
  competitive long run, price is driven down toward the *minimum average cost* — entry competes away
  excess profit. EVE’s commodity markets show this: a lucrative build attracts more manufacturers
  until margins normalise.

## In IndyOps

Supply is the sell side of every market view. In the **Market → Order Book / Orders** tabs, the
resting **sell orders** are standing supply — their depth and the lowest ask are the supply curve made
concrete. On the production side, the **Calculator** and **Chain** tools compute an item’s **marginal
cost of manufacture** — materials + fees + job cost — which *is* the floor of its supply curve and the
level the 0.01 ISK undercut war grinds toward. When you decide whether to build, you are deciding
whether the market price clears your marginal cost: supply meeting demand, one build at a time.`,
  quiz: [
    { q: 'Supply is best described as…', answer: 2,
      options: ['Today’s sell volume', 'The amount of ISK in the economy', 'A relationship between price and the quantity sellers will offer', 'A single fixed number'] },
    { q: 'The law of supply says the supply curve…', answer: 0,
      options: ['Slopes up (higher price → more offered)', 'Slopes down', 'Is flat', 'Is vertical always'] },
    { q: 'In competitive markets, the supply curve essentially traces a seller’s…', answer: 1,
      options: ['Average revenue', 'Marginal cost', 'Sales tax', 'Blueprint ME'],
      explain: 'Sellers offer each unit whose marginal cost is below the price — so supply ≈ the MC curve.' },
    { q: 'A change in the item’s OWN price causes…', answer: 0,
      options: ['A movement along the supply curve', 'A leftward shift', 'A rightward shift', 'No effect'] },
    { q: 'Cheaper inputs or better technology cause supply to…', answer: 3,
      options: ['Move up along the curve', 'Become vertical', 'Shift left', 'Shift right (more supplied at every price)'] },
    { q: 'Producer surplus is…', answer: 2,
      options: ['The sales tax', 'Total revenue', 'The gap between the price received and sellers’ marginal cost (their gain from trade)', 'The bid-ask spread'] },
    { q: 'Supply is INELASTIC when…', answer: 1,
      options: ['Producers have lots of spare capacity', 'Output can’t respond quickly (fixed capacity, long build times)', 'There are many sellers', 'Inputs are cheap'] },
    { q: 'In the competitive LONG run, entry of new sellers tends to drive price toward…', answer: 3,
      options: ['Infinity', 'Zero', 'The monopoly price', 'Minimum average cost (excess profit is competed away)'] },
    { q: 'An EVE item bottlenecked on a rare input with a long build timer has supply that is…', answer: 0,
      options: ['Inelastic — its price spikes when demand jumps', 'Perfectly elastic', 'Independent of cost', 'Always rightward-shifting'] },
    { q: 'Below average variable cost, a short-run competitive seller should…', answer: 2,
      options: ['Always keep producing', 'Raise the price', 'Stop producing (it’s not worth the variable cost)', 'Buy the blueprint'] },
    { q: 'In IndyOps, the resting SELL orders in the Order Book represent…', answer: 1,
      options: ['Standing demand', 'Standing supply (the supply curve made concrete)', 'The tax', 'The forecast'] },
    { q: 'The Calculator/Chain marginal cost of manufacture is, economically, the…', answer: 0,
      options: ['Floor of the item’s supply curve', 'Consumer surplus', 'Bid-ask spread', 'Elasticity'] },
  ],
}

const marketEquilibrium = {
  key: 'market-equilibrium',
  title: 'Market Equilibrium & Price Discovery',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Foundations → Intermediate',
  difficulty: 2,
  summary: 'How supply and demand together set the price. The clearing price, surplus and shortage, comparative statics (what happens when a curve shifts), and how real markets actually discover the price — including EVE’s order-book tâtonnement and the 0.01 ISK grind.',
  body: `# Market Equilibrium & Price Discovery

A market price is not announced — it is *found*, at the one level where the quantity buyers want
equals the quantity sellers offer. That level is the **equilibrium** (market-clearing) price, and the
process that gropes toward it is **price discovery**.

> Demand says how much buyers want at each price; supply says how much sellers offer. Equilibrium is
> the single price where the two agree — and price discovery is how the market gets there.

## The clearing price

Overlay the downward demand curve and the upward supply curve. They cross once, at the **equilibrium
price** \`P*\` and **quantity** \`Q*\`. At \`P*\`, every buyer willing to pay it is matched with a
seller willing to accept it; the market *clears*, with no unmet buyer or unsold unit at that price.

## Surplus and shortage push the price back

Equilibrium is **stable** because away from it, pressure builds toward it:

- **Above \`P*\`** — sellers offer more than buyers want: a **surplus** (glut). Unsold stock forces
  sellers to cut prices, pushing back down toward \`P*\`.
- **Below \`P*\`** — buyers want more than sellers offer: a **shortage**. Competing buyers bid the
  price up toward \`P*\`.

[[fig:surplusShortage|Set the price above the clearing level and quantity supplied exceeds quantity demanded — a surplus (the white gap). The glut forces the price back down. Below clearing, a shortage pushes it up.]]

This self-correction is Adam Smith’s **invisible hand**: no central planner sets the price; the
independent actions of buyers and sellers chasing their own gain drive it to the level that clears.

## Comparative statics — reading a shift

The real power of the model is predicting *change*. When a curve shifts, the equilibrium moves in a
predictable direction:

- **Demand ↑ (shift right):** \`P*\` up, \`Q*\` up. A hull becomes meta → its price and traded volume
  both rise.
- **Demand ↓:** \`P*\` down, \`Q*\` down.
- **Supply ↑ (shift right):** \`P*\` down, \`Q*\` up. A build gets cheaper → price falls, more trades.
- **Supply ↓:** \`P*\` up, \`Q*\` down. A key input gets scarce → price spikes, volume drops.

[[fig:equilibriumShift|A rightward demand shift (D₀→D₁) slides the equilibrium up the supply curve: both the clearing price and the traded quantity rise. Comparative statics reads the direction of change off the shift.]]

When *both* curves move, price or quantity may be determined but the other ambiguous — you need the
relative sizes of the shifts.

## How real markets discover the price

The textbook crossing is the *destination*; real markets reach it by a groping process Walras called
**tâtonnement** ("trial and error"). Bids and offers are posted, partial trades happen, and the price
is nudged until supply and demand balance. Different mechanisms do this differently:

- **Auctions** — bids reveal willingness to pay; the clearing price emerges from competition.
- **Continuous double auction** (stock exchanges, **EVE’s markets**) — a live order book where the
  best bid and ask converge as traders post, undercut and lift. Price discovery is *continuous*.

## EVE’s price discovery — the 0.01 ISK grind

EVE is a continuous double auction, so price discovery happens in the book. Because winning a sale
only needs you to beat the best ask by the smallest tick, sellers **undercut by 0.01 ISK**
repeatedly, walking the price down toward the **marginal-cost-plus-fees floor** — the competitive
equilibrium. Buyers do the mirror on the bid side. The result is a price that hovers right at the
clearing level, rediscovered minute by minute as inventory and demand shift. Broker and relist fees
are the friction that stops the grind from overshooting.

## Why equilibrium analysis is so useful

It turns "the price went up" from a mystery into a question with an answer: *which curve moved, and
why?* A price spike with rising volume is a demand story; a spike with falling volume is a supply
story. That single diagnostic — read straight off price-and-volume — is the backbone of market
analysis.

## In IndyOps

Every Market Browser view is equilibrium made visible. The **Order Book** shows the live bid/ask
converging on the clearing price; the **History** tab’s price *and* volume together let you run
comparative statics by eye — price up + volume up = demand shift; price up + volume down = supply
shift. The **Demand** and **Prediction** tabs quantify and project the demand side of that balance, and
the **trade/haul** tools exploit the moments when a market is *away* from equilibrium across regions
(see *Arbitrage & the Law of One Price*).`,
  quiz: [
    { q: 'The equilibrium (market-clearing) price is where…', answer: 1,
      options: ['Supply is largest', 'Quantity demanded equals quantity supplied', 'The price is highest', 'Volume is zero'] },
    { q: 'If the price is set ABOVE equilibrium, the result is…', answer: 0,
      options: ['A surplus (glut) that pushes the price down', 'A shortage', 'Exact clearing', 'Higher demand'] },
    { q: 'If the price is set BELOW equilibrium…', answer: 2,
      options: ['A surplus forms', 'Nothing happens', 'A shortage forms and buyers bid the price up', 'Sellers exit'] },
    { q: 'The "invisible hand" refers to…', answer: 3,
      options: ['A central price-setter', 'The sales tax', 'A trading bot', 'Self-interested buyers and sellers driving the price to the clearing level'] },
    { q: 'A rightward shift in DEMAND moves the equilibrium to…', answer: 0,
      options: ['Higher price, higher quantity', 'Lower price, lower quantity', 'Higher price, lower quantity', 'No change'] },
    { q: 'A rightward shift in SUPPLY (cheaper build) moves the equilibrium to…', answer: 1,
      options: ['Higher price, lower quantity', 'Lower price, higher quantity', 'Higher price, higher quantity', 'No change'] },
    { q: 'Using supply & demand to predict the direction of change after a shift is called…', answer: 2,
      options: ['Tâtonnement', 'Arbitrage', 'Comparative statics', 'Discounting'] },
    { q: 'A price spike accompanied by RISING volume is most likely…', answer: 0,
      options: ['A demand-side story (demand shifted right)', 'A supply-side story (supply shifted left)', 'A tax change', 'A measurement error'] },
    { q: 'A price spike accompanied by FALLING volume is most likely…', answer: 1,
      options: ['A demand increase', 'A supply-side story (supply shifted left)', 'No change in either curve', 'A demand decrease'] },
    { q: 'Walras’ "tâtonnement" describes…', answer: 3,
      options: ['A type of tax', 'A blueprint', 'The monopoly price', 'The trial-and-error groping toward the clearing price'] },
    { q: 'EVE discovers price mainly through…', answer: 2,
      options: ['A daily fixed price', 'A sealed auction', 'A continuous double auction (the live order book)', 'A central bank'] },
    { q: 'In EVE, the 0.01 ISK undercut grind drives the price toward…', answer: 0,
      options: ['The marginal-cost-plus-fees competitive floor', 'Zero', 'The monopoly price', 'Infinity'] },
    { q: 'What stops the undercut grind from overshooting below the floor?', answer: 1,
      options: ['A CCP price cap', 'Broker and relist fees (friction)', 'The blueprint ME', 'Nothing'] },
  ],
}

const elasticityArt = {
  key: 'elasticity',
  title: 'Elasticity',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'How sharply quantity responds to a change in price (or income, or another good’s price). Price elasticity and the total-revenue test, what makes demand elastic, income and cross-price elasticity (substitutes & complements), and elasticity of supply.',
  body: `# Elasticity

**Elasticity** measures *responsiveness*: when one thing changes by a percent, by how many percent does
another respond? It is the single most useful number for *acting* on supply and demand, because it
tells you whether a price move will help or hurt — and by how much.

> Slope tells you direction; elasticity tells you *magnitude*, in scale-free percentage terms you can
> compare across wildly different goods.

## Price elasticity of demand

The headline measure is **price elasticity of demand**:
\`E = (%ΔQ_demanded) / (%ΔP)\`. By the law of demand it’s (almost) always negative, so we usually quote
the magnitude \`|E|\`:

- **Elastic** (\`|E| > 1\`) — quantity reacts *more* than price. Buyers flee a price rise. Luxuries,
  faction toys, easily-substituted goods.
- **Inelastic** (\`|E| < 1\`) — quantity reacts *less* than price. Buyers stay. Necessities, fuel,
  common ammo, things with no substitute.
- **Unit elastic** (\`|E| = 1\`) — quantity and price move proportionally; revenue is unchanged.

[[fig:elasticity|Inelastic demand (amber, steep): quantity barely moves with price. Elastic demand (blue, flat): small price moves swing quantity hard. The flatter the curve, the more elastic.]]

## The total-revenue test

Elasticity decides whether cutting the price *raises* revenue (\`revenue = P × Q\`):

- Where demand is **elastic**, a price cut sells enough extra units to *grow* revenue — and a price
  hike shrinks it.
- Where demand is **inelastic**, a price cut just leaves money on the table — revenue *falls*; a hike
  raises it.
- Revenue peaks at **unit elasticity**.

[[fig:elasticityRevenue|Total revenue (P×Q) rises as you cut price through the elastic region, peaks at |E| = 1, then falls in the inelastic region. The total-revenue test reads elasticity straight off which way revenue moved.]]

This is why a monopolist never prices in the inelastic region, and why "should I undercut harder?"
depends entirely on the elasticity of *your* item.

## What makes demand elastic?

- **Substitutes** — the more (and closer) the alternatives, the more elastic. A specific T1 module
  with five near-identical variants is elastic; a unique faction module is not.
- **Necessity vs luxury** — must-haves are inelastic; nice-to-haves are elastic.
- **Share of budget** — items that eat a big chunk of spend are watched more closely (more elastic).
- **Time horizon** — demand is more elastic in the long run, as buyers find substitutes and adjust.

## Income elasticity

**Income elasticity** \`E_income = (%ΔQ) / (%Δincome)\` classifies goods by how demand responds to
wealth: **normal goods** rise with income (\`E > 0\`), **luxury goods** rise *more* than proportionally
(\`E > 1\`), and **inferior goods** *fall* as income rises (\`E < 0\`). In EVE, as a player’s wealth
grows they shift from T1 frigates to faction and capital hulls — the luxuries have high income
elasticity.

## Cross-price elasticity — substitutes and complements

**Cross-price elasticity** \`E_xy = (%ΔQ_x) / (%ΔP_y)\` measures how good X’s demand responds to good
Y’s *price*:

- **Substitutes** (\`E_xy > 0\`): Y gets pricier → buyers switch to X, so X’s demand rises. Two
  competing ammo types; T1 vs T2 when T2 is dear.
- **Complements** (\`E_xy < 0\`): Y gets pricier → people buy less of the *pair*, so X’s demand falls.
  Ships and the modules that fit them; guns and their ammo.

[[fig:crossPrice|Substitutes (left, positive): a higher price for A lifts demand for its alternative B. Complements (right, negative): a higher price for A drags down demand for the good B used alongside it.]]

## Elasticity of supply

Supply has elasticity too: \`E_s = (%ΔQ_supplied) / (%ΔP)\` — high when producers can ramp output fast
(spare slots, stockpiled inputs), low when they’re capacity- or input-constrained. When *both* sides
are inelastic, small shocks cause violent price swings — exactly the markets where a demand spike
(say, a war) sends prices vertical.

## In IndyOps

Elasticity is the lens behind several tools. The **Group Analysis** tab’s return-correlations hint at
**substitutes and complements** (items that move together vs against each other). The **Demand** tab’s
price-vs-volume relationship is empirical elasticity — does volume react to price? And the demand
**Prediction** of "how much can I sell at roughly what price" is, at heart, an elasticity question:
the quantity you can move is the demand curve, and elasticity is its shape.`,
  quiz: [
    { q: 'Elasticity measures…', answer: 2,
      options: ['The absolute price', 'The blueprint ME', 'Responsiveness — the % change in one variable per % change in another', 'The total volume'] },
    { q: 'Price elasticity of demand E = (%ΔQ)/(%ΔP). Demand is ELASTIC when…', answer: 0,
      options: ['|E| > 1 (quantity reacts more than price)', '|E| < 1', 'E = 0', 'E is positive'] },
    { q: 'Inelastic demand (|E| < 1) is typical of…', answer: 1,
      options: ['Easily-substituted luxuries', 'Necessities with no close substitute (fuel, common ammo)', 'Faction toys', 'Goods with many alternatives'] },
    { q: 'Cutting the price RAISES total revenue when demand is…', answer: 3,
      options: ['Inelastic', 'Unit elastic', 'Vertical', 'Elastic'] },
    { q: 'Total revenue (P×Q) is maximised at…', answer: 2,
      options: ['Zero elasticity', 'Infinite elasticity', 'Unit elasticity (|E| = 1)', 'The highest price'] },
    { q: 'Which makes demand MORE elastic?', answer: 0,
      options: ['Having many close substitutes', 'Being a necessity', 'A tiny share of the budget', 'A very short time horizon'] },
    { q: 'Demand tends to be more elastic in the…', answer: 1,
      options: ['Short run', 'Long run (buyers find substitutes and adjust)', 'Same in both', 'Neither'] },
    { q: 'A good whose demand FALLS as income rises is…', answer: 3,
      options: ['A luxury good', 'A normal good', 'A complement', 'An inferior good'] },
    { q: 'Luxury goods have income elasticity…', answer: 0,
      options: ['Greater than 1 (demand rises more than proportionally with income)', 'Negative', 'Exactly zero', 'Less than −1'] },
    { q: 'Cross-price elasticity E_xy > 0 means X and Y are…', answer: 2,
      options: ['Complements', 'Unrelated', 'Substitutes (Y pricier → buy more X)', 'Inferior goods'] },
    { q: 'Ships and the modules fitted to them are…', answer: 1,
      options: ['Substitutes (positive cross-elasticity)', 'Complements (negative cross-elasticity)', 'Inferior goods', 'Perfectly inelastic'] },
    { q: 'When BOTH supply and demand are inelastic, a demand shock causes…', answer: 0,
      options: ['Violent price swings', 'No price change', 'A guaranteed surplus', 'Lower volatility'] },
    { q: 'In IndyOps, "how much can I sell at roughly what price" is fundamentally a question about…', answer: 3,
      options: ['The sales tax', 'Blueprint ME', 'The risk-free rate', 'Elasticity — the shape of the demand curve'] },
  ],
}

const surplus = {
  key: 'surplus-welfare',
  title: 'Consumer & Producer Surplus',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'Why voluntary trade creates value. Consumer surplus, producer surplus, total welfare, why the competitive equilibrium is efficient, and how a tax (EVE’s broker fee + sales tax) drives a wedge that creates deadweight loss.',
  body: `# Consumer & Producer Surplus

Trade is not zero-sum. When a buyer who values a thing at 100 buys it for 70 from a seller whose cost
is 50, *both* gain — the buyer banks 30, the seller 20, and 50 of value is created from nothing but the
exchange. **Surplus** is the accounting of those gains, and it’s how economists judge whether a market
outcome is *good*, not just what price it lands on.

> Price tells you *where* the market clears; surplus tells you *how much value* the trade created — and
> who captured it.

## Consumer surplus

Each buyer has a private **willingness to pay** (WTP) — the most they’d give. The demand curve is just
all buyers’ WTP, ranked high to low. **Consumer surplus (CS)** is the total
\`WTP − price paid\`, summed over everyone who buys: the area *below the demand curve and above the
price*. A buyer who’d have paid 100 but pays 70 pockets 30 of surplus.

## Producer surplus

Symmetrically, each seller has a **minimum acceptable price** — their marginal cost. The supply curve
is those costs ranked low to high. **Producer surplus (PS)** is the total
\`price received − cost\`, the area *above the supply curve and below the price*. A seller whose cost
is 50 selling at 70 banks 20.

[[fig:surplusAreas|At the equilibrium price, consumer surplus (green) is the area below demand and above the price; producer surplus (blue) is above supply and below the price. Their sum is total welfare — and it is maximised exactly at the competitive equilibrium.]]

## Total welfare and why competition is efficient

**Total welfare** = consumer surplus + producer surplus — the whole pie of gains from trade. Here is
the deep result: at the **competitive equilibrium**, total welfare is **maximised**. Every trade whose
value (WTP) exceeds its cost happens, and no trade whose cost exceeds its value does. The market, left
alone, squeezes out *all* the mutually-beneficial trades and stops exactly where the last unit’s value
equals its cost. This is the **efficiency** of competitive markets — the rigorous version of the
invisible hand.

> "Efficient" here means *no value left on the table*, not *fair*. Efficiency is about the size of the
> pie; how it’s split between CS and PS is a separate question.

## Taxes drive a wedge — deadweight loss

Now put a **tax** between buyer and seller. Buyers pay \`P_buyer\`, sellers receive
\`P_seller = P_buyer − tax\`. The gap is the **tax wedge**. Because buyers face a higher price and
sellers a lower one, **fewer units trade** — and the trades that *don’t* happen were ones whose value
exceeded their cost. That lost surplus, captured by *no one* (not even the taxer), is **deadweight
loss**: pure destroyed value.

[[fig:deadweightLoss|A tax wedge separates the price buyers pay from what sellers receive, shrinking the quantity traded below the efficient Q*. The red triangle — trades that were worth doing but now don’t happen — is deadweight loss: value destroyed, captured by nobody.]]

Tax revenue itself isn’t deadweight (it’s transferred, not destroyed); the deadweight loss is only the
*missing trades*. The more **elastic** supply and demand, the bigger the quantity drop and the larger
the deadweight loss — which is why economists prefer taxing inelastic things.

## EVE’s wedge: broker fee + sales tax

EVE’s market taxes are a textbook wedge. Place a sell order and you pay a **broker fee**; complete the
sale and you pay **sales tax**. Together they separate what the buyer pays from what you net — exactly
\`P_seller = P_buyer − fees\`. The consequences are real: the fees set the **floor** the undercut war
grinds toward (you can’t profitably sell below cost + fees), they shrink the volume of marginal trades
(deadweight loss), and skills/standings that *lower* your fees narrow the wedge and hand you more of
the surplus. Every margin calculation in the toolset is, underneath, a surplus-after-the-wedge sum.

## In IndyOps

Surplus thinking is baked into the economics tools. Every **Calculator / Trade** margin is producer
surplus net of the EVE tax wedge — \`sell price − cost − broker − sales tax\`. The **trade optimizer**
ranks opportunities by exactly that after-fee surplus, and trading-character **skills and standings**
that cut broker/sales fees show up directly as a narrower wedge and a bigger slice of the gains from
trade. When you compare "patient" vs "instant" margins, you’re comparing how much surplus you keep for
the liquidity you give up (the spread).`,
  quiz: [
    { q: 'Voluntary trade is…', answer: 1,
      options: ['Zero-sum (one wins, one loses)', 'Positive-sum (both can gain — surplus is created)', 'Always a loss', 'Only good for sellers'] },
    { q: 'Consumer surplus is…', answer: 2,
      options: ['The sales tax', 'Total revenue', 'Willingness to pay minus the price paid, summed over buyers (area below demand, above price)', 'The bid-ask spread'] },
    { q: 'Producer surplus is the area…', answer: 0,
      options: ['Above the supply curve and below the price', 'Below demand and above price', 'Under the tax', 'Equal to total cost'] },
    { q: 'Total welfare equals…', answer: 3,
      options: ['Revenue minus cost', 'Just consumer surplus', 'The tax revenue', 'Consumer surplus + producer surplus'] },
    { q: 'A key result is that total welfare is MAXIMISED at…', answer: 1,
      options: ['The monopoly price', 'The competitive equilibrium', 'A price ceiling', 'Zero output'] },
    { q: '"Efficient" in this welfare sense means…', answer: 2,
      options: ['The split is fair', 'Sellers win', 'No mutually-beneficial trade is left undone (no value on the table)', 'Prices are lowest'] },
    { q: 'A tax between buyer and seller creates a…', answer: 0,
      options: ['Wedge: buyers pay more, sellers receive less, fewer units trade', 'Surplus for both', 'Higher equilibrium quantity', 'Lower price for buyers'] },
    { q: 'Deadweight loss is…', answer: 3,
      options: ['The tax revenue collected', 'Producer surplus', 'Consumer surplus', 'The value of mutually-beneficial trades that no longer happen — destroyed, captured by no one'] },
    { q: 'Tax REVENUE itself is…', answer: 1,
      options: ['Deadweight loss', 'A transfer, not destroyed value', 'Always larger than the deadweight loss', 'Consumer surplus'] },
    { q: 'Deadweight loss from a tax is LARGER when supply and demand are…', answer: 0,
      options: ['More elastic (quantity drops a lot)', 'Perfectly inelastic', 'Vertical', 'Unrelated to elasticity'] },
    { q: 'EVE’s broker fee + sales tax act economically as…', answer: 2,
      options: ['A subsidy', 'Consumer surplus', 'A tax wedge between what the buyer pays and what the seller nets', 'A price floor set by CCP'] },
    { q: 'Skills/standings that lower your broker and sales fees…', answer: 1,
      options: ['Widen the wedge', 'Narrow the wedge and hand you more surplus', 'Have no effect', 'Increase deadweight loss for you'] },
    { q: 'In IndyOps, a trade margin (sell − cost − broker − sales tax) is essentially…', answer: 0,
      options: ['Producer surplus net of the EVE tax wedge', 'Consumer surplus', 'The risk-free rate', 'The elasticity'] },
  ],
}

const costStructures = {
  key: 'cost-structures',
  title: 'Cost Structures: Fixed, Variable & Marginal',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'Where supply comes from: a producer’s costs. Fixed vs variable cost, marginal and average cost, the U-shaped cost curves, break-even, economies of scale, and how EVE manufacturing maps onto every one of these.',
  body: `# Cost Structures: Fixed, Variable & Marginal

Supply is governed by **cost**, and cost has structure. Splitting it into the right pieces — fixed,
variable, marginal, average — is what turns "is this build worth it?" from a guess into arithmetic, and
it’s the foundation under the supply curve.

> The two questions every producer answers: *how much does one more unit cost (marginal)?* and *what’s
> my cost per unit at this scale (average)?* Almost everything follows from those.

## Fixed vs variable cost

- **Fixed cost (FC)** — doesn’t change with output: it’s there whether you make 0 units or 1000. A
  blueprint’s purchase, a structure’s fuel, a research investment. Spread over more units, fixed cost
  per unit *falls*.
- **Variable cost (VC)** — scales with output: materials, per-job install fees. Make twice as many,
  pay roughly twice the variable cost.
- **Total cost (TC)** = FC + VC.

In EVE: the blueprint (especially an expensive BPO or invented BPC run) and facility fuel are *fixed*;
the minerals/components and the per-job industry fee are *variable*.

## Marginal cost — the cost of one more

**Marginal cost (MC)** is the extra cost of producing *one more* unit: \`MC = ΔTC / ΔQ\`. It is the
single most important cost concept, because **rational output decisions are made at the margin** (next
article) and because **the supply curve is the marginal-cost curve**. MC ignores fixed cost entirely —
fixed cost is already spent and doesn’t change with the next unit.

## Average cost — cost per unit

**Average total cost (ATC or AC)** = \`TC / Q\`; **average variable cost (AVC)** = \`VC / Q\`. AC tells
you whether you’re profitable *on average* at a given scale; the gap between price and AC is your
per-unit margin.

## The U-shaped curves

Plot them against output and a characteristic picture appears: **AC and AVC are U-shaped**, and **MC
cuts through both at their minimum points**. Why?

- At low output, spreading fixed cost dominates → average cost falls.
- At high output, diminishing returns (congested slots, pricier marginal inputs) push marginal — and
  eventually average — cost back up.
- MC crosses AC at AC’s minimum: while MC is *below* AC it pulls the average down; once MC rises
  *above* AC, the average turns up. (The "if your next exam beats your average, your average rises"
  rule.)

[[fig:costCurves|The textbook cost curves: average total cost (green) and average variable cost (blue) are U-shaped, and marginal cost (red) slices through each at its minimum. Below its average, MC drags the average down; above it, MC pulls the average up.]]

## Break-even

You **break even** where total revenue equals total cost: \`TR = TC\`. With a price \`P\` and per-unit
variable cost \`v\`, the break-even quantity is \`Q_BE = FC / (P − v)\`, where \`(P − v)\` is the
**contribution margin** per unit — what each sale contributes toward covering fixed cost. Below
\`Q_BE\` you lose money; above it you profit.

[[fig:breakEven|Total revenue (green, through the origin) versus total cost (red, starting at fixed cost). They cross at the break-even quantity; the contribution margin per unit (price − variable cost) is what closes the fixed-cost gap.]]

## Economies (and diseconomies) of scale

**Economies of scale** exist when average cost *falls* with output — bigger batches spread fixed cost
and unlock efficiencies (a researched blueprint, a multi-run job, bulk input buying). **Diseconomies**
set in when AC eventually *rises* — slot bottlenecks, having to pay up for scarce marginal inputs,
crashing your own sell price by flooding the market. The **minimum efficient scale** is the output at
the bottom of the AC curve: produce there and your unit cost is as low as it gets.

## The shut-down rule

A subtlety from the fixed/variable split: in the short run, keep producing as long as price covers
**average *variable* cost**, even if it doesn’t cover total cost — because fixed cost is sunk either
way, and any contribution above VC reduces the loss. Stop only when \`P < AVC\`. This is why the
short-run supply curve is the MC curve *above AVC*.

## In IndyOps

This is exactly what the **Calculator** and **Chain** tools compute. A build’s **material cost + per-job
industry fee** is its variable cost; the **blueprint and facility/fuel** side is fixed; the engine
rolls them into a **marginal cost of manufacture** — the floor of the item’s supply curve and the level
the undercut war grinds toward. The **make-vs-buy** core compares your marginal cost of *making* an
input against the market price of *buying* it (the next article). And the **Monte-Carlo profit
simulator** treats fixed cost as a sunk lump and samples the variable side, so the loss distribution
respects the fixed/variable split.`,
  quiz: [
    { q: 'Fixed cost is cost that…', answer: 1,
      options: ['Scales with output', 'Doesn’t change with output (there whether you make 0 or 1000)', 'Equals marginal cost', 'Is always zero'] },
    { q: 'Which is a VARIABLE cost in EVE manufacturing?', answer: 2,
      options: ['The blueprint purchase', 'Structure fuel', 'Minerals / components and the per-job fee', 'A one-off research investment'] },
    { q: 'Marginal cost is…', answer: 0,
      options: ['The extra cost of producing one more unit (ΔTC/ΔQ)', 'Total cost / quantity', 'Fixed cost', 'The sales tax'] },
    { q: 'Marginal cost IGNORES…', answer: 3,
      options: ['Material cost', 'The per-job fee', 'Variable cost', 'Fixed cost (already spent, unchanged by the next unit)'] },
    { q: 'The supply curve is essentially the…', answer: 1,
      options: ['Average cost curve', 'Marginal cost curve', 'Fixed cost line', 'Demand curve'] },
    { q: 'Average cost curves are typically…', answer: 2,
      options: ['Always rising', 'Flat', 'U-shaped', 'Always falling'] },
    { q: 'Marginal cost crosses average cost at…', answer: 0,
      options: ['Average cost’s minimum point', 'The break-even quantity', 'Zero output', 'The monopoly price'] },
    { q: 'While MC is BELOW AC, the average cost is…', answer: 1,
      options: ['Rising', 'Falling (MC pulls the average down)', 'Constant', 'Negative'] },
    { q: 'Break-even quantity with price P and unit variable cost v is…', answer: 2,
      options: ['FC × (P − v)', 'P / v', 'FC / (P − v)', 'FC + VC'] },
    { q: 'The contribution margin per unit is…', answer: 0,
      options: ['Price minus variable cost (P − v)', 'Fixed cost', 'Total revenue', 'The tax'] },
    { q: 'Economies of scale mean average cost…', answer: 3,
      options: ['Rises with output', 'Equals marginal cost', 'Is fixed', 'Falls with output'] },
    { q: 'The short-run shut-down rule says keep producing as long as price covers…', answer: 1,
      options: ['Average total cost', 'Average variable cost (fixed cost is sunk either way)', 'Marginal revenue', 'The blueprint cost'] },
    { q: 'In IndyOps, the Calculator’s "marginal cost of manufacture" is, economically, the…', answer: 0,
      options: ['Floor of the item’s supply curve', 'Consumer surplus', 'Risk-free rate', 'Bid-ask spread'] },
  ],
}

const marginalAnalysis = {
  key: 'marginal-analysis',
  title: 'Marginal Analysis & Profit Maximisation',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'The single most powerful rule in microeconomics: do something until marginal benefit equals marginal cost. Marginal revenue vs marginal cost, the profit-maximising quantity, why sunk costs are irrelevant, and how it decides how much to build.',
  body: `# Marginal Analysis & Profit Maximisation

Most good decisions in economics are made not in totals but **at the margin** — by asking about the
*next* unit, not the whole batch. **Marginal analysis** is the discipline of comparing the **marginal
benefit** of one more with its **marginal cost**, and it yields the most powerful rule in all of
microeconomics.

> The rule, in one line: **do more while marginal benefit > marginal cost; stop where they’re equal.**
> Everything else is detail.

## Think at the margin, not in totals

"Should I build 100 of these?" is the wrong question. The right one is: "is the **next** one worth it?"
You keep building as long as each additional unit adds more revenue than it adds cost, and you stop at
the unit where they’re equal. The total profit takes care of itself if every marginal step was worth
taking.

## Marginal revenue vs marginal cost

- **Marginal revenue (MR)** — the extra revenue from selling one more unit.
- **Marginal cost (MC)** — the extra cost of making one more unit (from the previous article).

The **profit-maximising quantity \`Q*\`** is where **MR = MC**:

- If **MR > MC**, the next unit adds more than it costs → make it. Profit is still climbing.
- If **MR < MC**, the next unit costs more than it brings → don’t. You’ve overshot.
- At **MR = MC**, you’ve captured every profitable unit and none of the unprofitable ones.

[[fig:marginalRevenueCost|Profit is maximised where marginal revenue meets marginal cost. Left of Q*, MR > MC — each extra unit adds profit. Right of Q*, MC > MR — extra units destroy it. Q* is the sweet spot.]]

## Price-takers vs price-setters

The shape of MR depends on market power (see *Market Structures*):

- A **price-taker** (perfect competition — most EVE commodity sellers) faces a flat MR = the market
  price: you can sell all you want at the going price, so each unit brings in exactly P. Profit-max:
  produce where **MC = P**.
- A **price-setter** (monopoly / market power) faces a **downward-sloping MR below the demand curve**:
  to sell more you must cut the price on *all* units, so MR < P. It restricts output and prices above
  MC (covered in *Market Structures*).

## Sunk costs are irrelevant

A corollary that trips everyone up: **sunk costs don’t matter** for the next decision. Money already
spent — a blueprint you bought, research you paid for — is gone whether or not you produce; it doesn’t
change the *marginal* comparison. Only costs that *change with the decision* count. "But I already
invested so much" is the **sunk-cost fallacy**; marginal analysis immunises you against it. (Fixed cost
matters for whether the whole venture was worth starting — not for the next unit.)

## Marginal thinking everywhere

The rule generalises far beyond output: buy inputs until the marginal product per ISK is equal across
them; invest in research/ME until the marginal saving equals the marginal cost; haul one more unit
while marginal profit beats marginal freight. Wherever you’re choosing "how much," the answer is "until
marginal benefit = marginal cost."

## In IndyOps

Marginal analysis underpins the production and trade decisions. The **Calculator/Chain** give you the
**marginal cost** of a build; comparing it to the market **price** (your marginal revenue as a
price-taker) is exactly the MC = P profit-max test — and the **make-vs-buy** core applies the same
logic input-by-input (make while your marginal cost of making < the price of buying). The **trade
optimizer** ranks by per-unit (marginal) margin, and the **haul** liquidity cap is a marginal-thinking
guard: keep allocating to an item only while the next unit can still be sold without crashing the
price. And because the tools separate fixed from variable cost, they keep **sunk costs out of the
marginal decision** — as they should.`,
  quiz: [
    { q: 'Marginal analysis compares…', answer: 2,
      options: ['Total revenue with total cost only', 'Average cost with price', 'The marginal benefit of one more with its marginal cost', 'Fixed cost with variable cost'] },
    { q: 'The profit-maximising quantity Q* is where…', answer: 0,
      options: ['Marginal revenue equals marginal cost (MR = MC)', 'Total cost is lowest', 'Price is highest', 'Fixed cost = 0'] },
    { q: 'If MR > MC at the current output, you should…', answer: 1,
      options: ['Produce less', 'Produce more (the next unit adds profit)', 'Stop entirely', 'Raise fixed cost'] },
    { q: 'If MR < MC, the next unit…', answer: 3,
      options: ['Adds profit', 'Is free', 'Has no effect', 'Costs more than it brings in — don’t make it'] },
    { q: 'A price-taker (perfect competition) faces a marginal revenue that is…', answer: 0,
      options: ['Flat and equal to the market price', 'Downward-sloping below demand', 'Always rising', 'Zero'] },
    { q: 'For a price-taker, the profit-max condition simplifies to…', answer: 2,
      options: ['MR = 0', 'P = AC', 'MC = P (produce where marginal cost equals the price)', 'FC = VC'] },
    { q: 'A price-setter (market power) has marginal revenue that is…', answer: 1,
      options: ['Equal to the price', 'Below the price (to sell more it must cut price on all units)', 'Always flat', 'Negative always'] },
    { q: 'Sunk costs should be…', answer: 3,
      options: ['Added to marginal cost', 'Doubled', 'The main driver of the next decision', 'Ignored for the next decision (they don’t change with it)'] },
    { q: '"I’ve already invested so much, I should keep going" is the…', answer: 0,
      options: ['Sunk-cost fallacy', 'Law of demand', 'Break-even rule', 'Comparative advantage'] },
    { q: 'Marginal analysis says to allocate spending across inputs until…', answer: 1,
      options: ['One input is fully used', 'The marginal product per ISK is equal across them', 'The cheapest input is exhausted', 'Fixed cost is zero'] },
    { q: 'In IndyOps, comparing a build’s marginal cost to the market price is…', answer: 2,
      options: ['A sunk-cost calculation', 'The bid-ask spread', 'The MC = P profit-max test for a price-taker', 'An elasticity estimate'] },
    { q: 'The make-vs-buy core decides to MAKE an input when…', answer: 0,
      options: ['Your marginal cost of making it is below the price of buying it', 'You already own the blueprint', 'The item is taxed', 'The forecast is rising'] },
  ],
}

const opportunityCost = {
  key: 'opportunity-cost',
  title: 'Opportunity Cost & Comparative Advantage',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate',
  difficulty: 2,
  summary: 'The real cost of anything is what you give up. Opportunity cost, the production-possibilities frontier, comparative vs absolute advantage, why specialisation and trade beat self-sufficiency — and why that’s exactly the logic of make-vs-buy.',
  body: `# Opportunity Cost & Comparative Advantage

The real cost of a choice is not the ISK you spend — it’s the **best alternative you give up**. That
idea, **opportunity cost**, is the most under-used concept in practical decision-making, and it leads
straight to the most counter-intuitive result in economics: **comparative advantage**, the reason
specialisation and trade beat doing everything yourself.

> Opportunity cost: the value of the road not taken. Every "yes" is a "no" to the best thing you could
> have done with the same time, ISK or factory slot.

## Opportunity cost

Spend 10M ISK and a factory slot building widget A, and the cost isn’t just 10M — it’s the profit you
*would* have made building gadget B in that same slot. Resources are scarce (you have finite ISK,
slots, time), so using them one way *forecloses* another. The right comparison for any decision is
always against its **next-best use**, not against zero.

This reframes everything: a "free" reaction slot isn’t free if it could have run something more
profitable; cheap minerals tied up in a slow build carry the opportunity cost of the trades you
couldn’t fund. Good operators think in opportunity costs reflexively.

## The production-possibilities frontier

Picture all the combinations of two goods you *could* produce with your fixed resources. The boundary
is the **production-possibilities frontier (PPF)**. Points *on* it are **efficient** (no idle slots);
points *inside* are wasteful (slack); points *outside* are unreachable with current resources.

[[fig:ppf|The production-possibilities frontier. On the curve = efficient (resources fully used); inside = slack; outside = unreachable. Its slope is the opportunity cost — to make more of one good you slide along the curve and give up some of the other.]]

The PPF’s **slope is the opportunity cost**: to make one more ship you must give up some modules, and
the curve tells you how many. Its outward *bow* reflects that resources aren’t equally good at
everything — pushing all-in on one good gets progressively costlier (increasing opportunity cost).

## Absolute vs comparative advantage

- **Absolute advantage** — you can produce a good using *fewer resources* than someone else.
- **Comparative advantage** — you can produce it at a *lower opportunity cost* than someone else.

The stunning result (David Ricardo, 1817): **trade is governed by comparative, not absolute,
advantage.** Even if you’re better at producing *everything* (absolute advantage in all), you still
gain by specialising in what you’re *comparatively* best at and **buying the rest** — because your time
spent on the thing you’re only slightly better at carries a high opportunity cost.

[[fig:comparativeAdvantage|Opportunity cost decides who makes what. Whoever can produce a good by giving up the least (green, low opportunity cost) should specialise in it; the other should buy it. Specialising by comparative advantage and trading beats both parties doing everything.]]

## Why specialisation and trade win

If each party specialises in their comparative-advantage good and trades for the rest, *total* output
rises and **both end up with more than self-sufficiency would allow**. This is the rigorous case for
the division of labour — and for *not* trying to vertically produce every input yourself just because
you *can*.

## Make-vs-buy is comparative advantage

This is exactly the **make-vs-buy** decision at the heart of industrial planning. For each input you
could either **make** it (incurring its marginal cost *and* the opportunity cost of the slot/time) or
**buy** it from the market. You should make an input only when your **all-in cost of making it
(including opportunity cost) is below the market price of buying it** — i.e. where you hold a
comparative advantage. Where the market makes it cheaper *relative to what else you could do*, buy it
and spend your slots on what you’re comparatively best at.

> The trap: "I have the blueprint, so I should make it." Owning the BPO is a sunk cost; the live
> question is the opportunity cost of the slot. Sometimes the right move is to buy the component and
> build something more valuable.

## In IndyOps

The **Chain calculator’s make-vs-buy core** *is* comparative advantage in code: it recursively compares,
for every node in a build tree, the cost of **making** each sub-component against **buying** it at
market, and chooses the cheaper branch — exactly Ricardo’s logic applied to a bill of materials. The
**OR-Tools slot assignment** layered on top handles the scarce-slot opportunity cost: with limited
factory/reaction slots, it allocates them to the highest-value jobs, so you specialise where your
advantage is greatest. Whenever the tool says "buy this component," it has found that the market holds
the comparative advantage for that input.`,
  quiz: [
    { q: 'Opportunity cost is…', answer: 1,
      options: ['The ISK price you pay', 'The value of the best alternative you give up', 'The sales tax', 'Always zero for owned items'] },
    { q: 'A "free" factory slot used for build A actually costs…', answer: 2,
      options: ['Nothing', 'Only the materials', 'The profit you’d have made using that slot for its next-best job', 'The blueprint price'] },
    { q: 'On the production-possibilities frontier, a point INSIDE the curve means…', answer: 0,
      options: ['Inefficiency / slack (resources not fully used)', 'Efficiency', 'Unreachable output', 'Maximum profit'] },
    { q: 'The SLOPE of the PPF represents…', answer: 3,
      options: ['Total cost', 'The tax rate', 'Demand', 'Opportunity cost (how much of one good you give up for the other)'] },
    { q: 'Absolute advantage means producing a good with…', answer: 1,
      options: ['A lower opportunity cost', 'Fewer resources than the other party', 'A higher price', 'More taxes'] },
    { q: 'Comparative advantage means producing a good at…', answer: 0,
      options: ['A lower opportunity cost than the other party', 'A higher absolute output', 'Zero cost', 'The monopoly price'] },
    { q: 'Ricardo’s result is that trade is governed by…', answer: 2,
      options: ['Absolute advantage', 'The sales tax', 'Comparative advantage (lower opportunity cost)', 'Whoever is richer'] },
    { q: 'Even if you’re better at producing EVERYTHING, you still gain by…', answer: 3,
      options: ['Producing it all yourself', 'Producing nothing', 'Raising your prices', 'Specialising where your comparative advantage is largest and buying the rest'] },
    { q: 'Specialising by comparative advantage and trading results in…', answer: 0,
      options: ['Both parties getting more than under self-sufficiency', 'One party losing', 'Lower total output', 'No change'] },
    { q: 'You should MAKE an input rather than buy it when…', answer: 1,
      options: ['You own the blueprint', 'Your all-in cost (including opportunity cost) is below the market price', 'It is taxed', 'The market price is rising'] },
    { q: '"I own the BPO, so I must make it" ignores…', answer: 2,
      options: ['The material cost', 'The sales tax', 'The opportunity cost of the slot (the BPO is a sunk cost)', 'The demand curve'] },
    { q: 'The IndyOps Chain make-vs-buy core is, conceptually…', answer: 0,
      options: ['Comparative advantage applied recursively to a bill of materials', 'A Monte-Carlo simulation', 'An elasticity estimate', 'A tax calculator'] },
  ],
}

const marketStructures = {
  key: 'market-structures',
  title: 'Market Structures',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate → Advanced',
  difficulty: 3,
  summary: 'How the number and power of sellers shapes price and behaviour, from perfect competition to monopoly. Price-takers vs price-setters, market power and the markup, monopoly’s deadweight loss, oligopoly — and where EVE’s markets actually sit.',
  body: `# Market Structures

The same supply-and-demand logic plays out very differently depending on *how many* sellers there are
and *how much power* each holds. **Market structure** classifies markets along that spectrum — from a
sea of tiny price-takers to a single price-setting monopolist — and it predicts price, output and
behaviour in each.

> The core variable is **market power**: can a seller move the price by changing its own output? In
> perfect competition, no. In monopoly, entirely. Everything in between is a matter of degree.

## The spectrum

[[fig:structureSpectrum|The market-structure spectrum, from many powerless price-takers (perfect competition) through monopolistic competition and oligopoly to a single price-setting monopoly. Market power rises as the number of sellers falls and products differentiate.]]

- **Perfect competition** — many sellers, identical product, free entry, full information. Each is a
  **price-taker**: too small to move the price, it accepts the market price and produces where
  **MC = P**. Long-run profit is competed to zero.
- **Monopolistic competition** — many sellers but *differentiated* products (branding, slight
  variations). Each has a sliver of power over its niche, but free entry still erodes profit long-run.
- **Oligopoly** — a *few* large sellers whose decisions affect each other; strategic interaction
  dominates (see *Game Theory*). Prices can be sticky or collusive.
- **Monopoly** — a single seller, a **price-setter** facing the whole downward demand curve.

## Price-taker vs price-setter

This is the pivotal distinction. A **price-taker** faces a flat marginal revenue equal to the market
price — it can sell all it wants at P, so MR = P and it produces where MC = P. A **price-setter** faces
the **downward-sloping demand curve**: to sell one more unit it must lower the price on *every* unit,
so its **marginal revenue is below the price** (MR < P). That gap is the source of everything that
makes monopoly different.

## Monopoly: restrict output, raise price

Because MR < P, the monopolist’s profit-max point (MR = MC) sits at a **lower quantity and higher
price** than the competitive outcome. It deliberately *restricts output* to push the price up the
demand curve.

[[fig:monopolyPricing|A monopolist sets output where MR = MC, then charges what the demand curve will bear at that quantity — a price above marginal cost. Compared to competition (P = MC), it produces less and charges more, creating deadweight loss.]]

The **markup** — price above marginal cost — is the visible fingerprint of market power; the
**Lerner index** \`(P − MC)/P\` quantifies it (0 in perfect competition, rising toward 1 with power).
And because some buyers who valued the good above its cost are now priced out, monopoly creates
**deadweight loss** — the efficiency cost of market power (see *Consumer & Producer Surplus*).

## Barriers to entry — what sustains power

Market power only persists if rivals *can’t* freely enter and compete it away. **Barriers to entry** —
high fixed/startup costs, exclusive access to an input, regulation, network effects, secret know-how —
are what protect a profitable position. Where entry is easy, even a temporary monopoly is bid back
toward competition.

## Where do EVE’s markets sit?

EVE is a fascinating natural experiment:

- **Commodity items** (minerals, common modules, fuel) are close to **perfect competition** — many
  anonymous sellers, identical goods, free entry, an open order book. The 0.01 ISK undercut war drives
  price to the competitive floor (MC + fees), and long-run margins are thin. Pure price-taking.
- **Niche / regional markets** can show real **market power**: a thin item in a quiet region, a
  freshly-invented hull, or a deliberately **cornered** market (a cartel buying out the book and
  relisting high) behaves monopolistically — restricted supply, a fat markup — until someone seeds
  competition and entry erodes it.
- **Production with a moat** — an expensive researched BPO, a rare blueprint, or exclusive moon access
  is a **barrier to entry** that sustains margin where others face thin competitive returns.

So the same toolset must handle both regimes: razor-thin competitive commodities and fat-margin niche
plays.

## In IndyOps

Structure shows up in how items behave across the tools. The **Demand** metrics (order count, depth,
imbalance) and **History** spreads reveal how *competitive* a market is — many tight orders and thin
margins signal price-taking; a wide spread with few orders signals power or illiquidity. The **trade
optimizer** hunts the inefficiencies that exist *because* markets aren’t perfectly competitive
everywhere (regional price gaps — see *Arbitrage*), and the production tools help you find the
**moated** builds (researched prints, rare inputs) where a barrier to entry lets a margin survive that
pure competition would erase.`,
  quiz: [
    { q: 'The core variable distinguishing market structures is…', answer: 2,
      options: ['The sales tax', 'The blueprint ME', 'Market power — can a seller move the price by changing its own output?', 'The colour of the item'] },
    { q: 'In perfect competition each seller is a…', answer: 0,
      options: ['Price-taker (too small to move the price)', 'Price-setter', 'Monopolist', 'Tax collector'] },
    { q: 'A price-taker produces where…', answer: 1,
      options: ['MR < MC', 'MC = P (marginal cost equals the market price)', 'P = 0', 'Output is maximal'] },
    { q: 'A price-setter (monopoly) faces a marginal revenue that is…', answer: 3,
      options: ['Equal to the price', 'Above the price', 'Flat', 'Below the price (must cut price on all units to sell more)'] },
    { q: 'Compared with competition, a monopolist…', answer: 0,
      options: ['Restricts output and charges a higher price', 'Produces more at a lower price', 'Charges exactly marginal cost', 'Has no market power'] },
    { q: 'The markup (P − MC) is the fingerprint of…', answer: 2,
      options: ['Perfect competition', 'A subsidy', 'Market power', 'Elastic demand'] },
    { q: 'The Lerner index (P − MC)/P equals roughly 0 when…', answer: 1,
      options: ['The firm is a monopoly', 'The market is perfectly competitive', 'Demand is inelastic', 'There is a tax'] },
    { q: 'Monopoly causes deadweight loss because…', answer: 3,
      options: ['It pays more tax', 'Its costs are higher', 'It has no fixed cost', 'Some buyers who valued the good above its cost are priced out'] },
    { q: 'Market power persists only when there are…', answer: 0,
      options: ['Barriers to entry (rivals can’t freely compete it away)', 'Low fixed costs', 'Many identical sellers', 'No regulations'] },
    { q: 'EVE’s common commodity markets (minerals, fuel) are closest to…', answer: 1,
      options: ['Monopoly', 'Perfect competition (many sellers, identical goods, free entry)', 'Oligopoly', 'A regulated market'] },
    { q: 'A cartel buying out a thin region’s order book and relisting high behaves like…', answer: 2,
      options: ['Perfect competition', 'A price-taker', 'A monopoly (restricted supply, fat markup) until entry erodes it', 'A tax'] },
    { q: 'An expensive researched BPO or rare blueprint acts as…', answer: 0,
      options: ['A barrier to entry that sustains margin', 'A sunk demand curve', 'A subsidy to rivals', 'A price ceiling'] },
    { q: 'A wide spread with very few orders most likely signals…', answer: 3,
      options: ['Perfect competition', 'A measurement error', 'Maximum liquidity', 'Market power or illiquidity (not price-taking)'] },
  ],
}

const arbitrage = {
  key: 'arbitrage',
  title: 'Arbitrage & the Law of One Price',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'Why the same thing tends to cost the same everywhere — and how profit-seekers enforce it. The law of one price, arbitrage, the no-arbitrage band set by transport and transaction costs, and how the trade/haul optimizer is arbitrage in action.',
  body: `# Arbitrage & the Law of One Price

If a Tritanium unit costs 5 ISK in one region and 6 in another, something is off — and someone is about
to get paid for fixing it. **Arbitrage** is the act of buying where a thing is cheap and selling where
it’s dear, and it’s the force that drags prices of the same good toward each other everywhere: the
**law of one price**.

> Arbitrage is the market’s immune system: wherever the same value carries two different prices,
> profit-seekers swarm the gap until (transaction costs aside) it closes.

## The law of one price

In a frictionless, competitive market, **identical goods must trade at the same price** — otherwise
everyone buys at the low price and sells at the high one until the prices meet. The law of one price is
the *consequence* of arbitrage, not an assumption: it holds because violating it is a money pump.

## Arbitrage

A pure **arbitrage** is a set of trades that earns a riskless profit with no net investment:
simultaneously buy low and sell high the same asset. Each act of arbitrage *pushes the two prices
together* — buying in the cheap market raises its price, selling in the dear market lowers it — so
arbitrage is **self-extinguishing**: doing it removes the opportunity that motivated it. That’s exactly
why persistent free lunches are rare; they get eaten.

## Frictions create a no-arbitrage *band*

Real arbitrage isn’t free. **Transaction and transport costs** mean prices needn’t be *equal*, only
within a **band** of each other. The law of one price becomes: \`|P_A − P_B| ≤ transport + fees\`.
Inside the band, the gap is too small to cover the cost of moving/trading, so no arbitrage flows and
the gap persists. Only when the gap *exceeds* the band does it become profitable — and arbitrage drags
it back to the band’s edge.

[[fig:arbitrageBand|Two regions’ prices. The shaded band around the Jita price is the transport-plus-fee cost. While the C-J price sits above the band there is a profitable haul; arbitrage (hauling) closes the gap down to the band’s edge, where moving one more unit no longer pays.]]

## The components of the band

For a haul between two markets the band is the *all-in cost of the round trip*:

- **Transport cost** — freight/courier per unit (volume × ISK-per-m³ × jumps), plus collateral risk.
- **Broker fee** on placing the sell order and **sales tax** on the sale.
- **Spread / slippage** — you buy at the ask and sell into the bid (or undercut), not at the mid.
- **Time and inventory risk** — the price can move while goods are in transit (this is what makes EVE
  hauling *not* a pure riskless arbitrage but a *statistical* one).

Subtract all of that from the raw price gap and what’s left is the real margin.

## Risk arbitrage vs pure arbitrage

EVE hauling is **risk arbitrage**, not textbook riskless arbitrage: the buy and sell aren’t
simultaneous (goods take time to move), the destination price can shift, and the cargo can be ganked.
So the "profit" is an *expected* margin with a variance — which is why the haul tools pair the margin
with **liquidity** and **risk** controls rather than treating it as a sure thing.

## Spatial, temporal and triangular arbitrage

- **Spatial** — same good, different *places* (Jita vs C-J). The haul case.
- **Temporal** — same good, different *times*: buy when cheap, hold, sell when dear. This shades into
  speculation and depends on a demand/price *forecast*.
- **Triangular / cross-good** — exploit mispricing across *related* goods (e.g. minerals vs the
  compressed ore vs the refined output, or build cost vs sell price). The make-vs-buy and reprocessing
  comparisons are cousins of this.

## In IndyOps

The **trade optimizer** and **Jita → C-J haul scanner** are arbitrage engines. They scan the price gap
for each item across hubs, subtract the **no-arbitrage band** (transport per m³, broker, sales tax,
and a liquidity-aware sell assumption), and surface only the items where the gap *clears* the band —
the profitable hauls. Because it’s **risk** arbitrage, they layer on the **liquidity cap** (can you
actually sell the volume?) and the **portfolio optimizer** (don’t bet the budget on one thin gap). The
build-vs-buy and reprocessing tools are cross-good arbitrage — buy the form of the value that’s
underpriced, sell or consume the form that’s dear.`,
  quiz: [
    { q: 'The law of one price says identical goods should…', answer: 0,
      options: ['Trade at the same price (frictions aside)', 'Always differ in price', 'Be taxed equally', 'Have the same blueprint'] },
    { q: 'Arbitrage is…', answer: 2,
      options: ['A type of tax', 'Holding an asset forever', 'Buying where cheap and selling where dear to capture the gap', 'Setting a monopoly price'] },
    { q: 'Arbitrage is "self-extinguishing" because…', answer: 1,
      options: ['It is illegal', 'Doing it pushes the two prices together, removing the opportunity', 'It needs huge capital', 'Prices never move'] },
    { q: 'With transaction/transport costs, prices need only be…', answer: 3,
      options: ['Exactly equal', 'Always different', 'Set by a monopolist', 'Within a band: |P_A − P_B| ≤ transport + fees'] },
    { q: 'Inside the no-arbitrage band, a price gap…', answer: 0,
      options: ['Persists (too small to cover the cost of acting)', 'Is always exploited', 'Becomes a tax', 'Triggers a monopoly'] },
    { q: 'Which is NOT part of an EVE haul’s no-arbitrage band?', answer: 2,
      options: ['Transport/freight per unit', 'Broker fee and sales tax', 'The blueprint ME', 'Spread / slippage'] },
    { q: 'EVE hauling is best described as…', answer: 1,
      options: ['Pure riskless arbitrage', 'Risk arbitrage (non-simultaneous, price can move, cargo can be ganked)', 'A monopoly', 'A subsidy'] },
    { q: 'Buying a good cheap in one region to sell dear in another is…', answer: 0,
      options: ['Spatial arbitrage', 'Temporal arbitrage', 'Triangular arbitrage', 'A tax'] },
    { q: 'Buying when cheap, holding, and selling later when dear is…', answer: 3,
      options: ['Spatial arbitrage', 'Pure arbitrage', 'A monopoly', 'Temporal arbitrage (shades into speculation, needs a forecast)'] },
    { q: 'Exploiting mispricing across minerals vs compressed ore vs refined output is…', answer: 1,
      options: ['Spatial arbitrage', 'Triangular / cross-good arbitrage', 'A tax wedge', 'Deadweight loss'] },
    { q: 'The trade/haul optimizer surfaces an item only when the price gap…', answer: 2,
      options: ['Is exactly zero', 'Equals the sales tax', 'Clears the no-arbitrage band (transport + fees + liquidity-aware sell)', 'Is inside the band'] },
    { q: 'Because hauling is RISK arbitrage, the tools also apply…', answer: 0,
      options: ['Liquidity and portfolio risk controls (not just the raw margin)', 'A monopoly markup', 'A price ceiling', 'A subsidy'] },
  ],
}

const marketMaking = {
  key: 'market-making',
  title: 'Market Making',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Advanced',
  difficulty: 3,
  summary: 'The business of providing liquidity for a living. Capturing the spread, the maker’s risks (inventory and adverse selection), why the spread must cover them, the 0.01 ISK game as professional market making, and how to run it as a real strategy.',
  body: `# Market Making

A **market maker** earns a living by doing what everyone else needs but few want to do: stand ready to
*both* buy and sell, continuously, and profit from the **spread** between the two. It is the
professional face of liquidity provision — and in EVE it’s called **station trading**.

> The market maker’s deal: provide immediacy to impatient traders, and get paid the bid-ask spread for
> it — as long as you manage the two risks that come with the job.

## Capturing the spread

The core mechanic is simple to state. Post a **buy order** at the bid and a **sell order** at the ask.
When an impatient buyer crosses your ask and an impatient seller hits your bid, you’ve bought low and
sold high *the same item* — pocketing the **spread** as gross profit per unit, without ever betting on
the price direction.

[[fig:spreadCapture|Market making: rest a buy order at the bid and a sell order at the ask. Buy when someone hits your bid, sell when someone lifts your ask — the spread between them is your gross profit per unit, earned by providing liquidity rather than predicting price.]]

Run thousands of these and small per-unit spreads add up. The market maker doesn’t need the price to
go anywhere — only for it to *oscillate* enough that both sides get filled.

## The two risks the spread must pay for

The spread isn’t free money; it’s **compensation for two real risks** (the same ones that *create* the
spread — see *Order Book Microstructure*):

- **Inventory risk.** Fills are random. You might buy a pile before selling any, leaving you **long**
  an unwanted position whose price can fall before you offload it. A maker must actively manage
  inventory back toward neutral — skewing quotes (bid lower / ask lower) to encourage the fills that
  rebalance.
- **Adverse selection.** You quote to *everyone*, including the better-informed. When news hits, the
  informed pick off your stale quote — they lift your ask just before the price jumps, or hit your bid
  just before it drops. You systematically trade against information and lose on those fills. The
  spread must be wide enough that profits from uninformed flow cover these losses.

A market maker is profitable only when **spread captured > inventory losses + adverse-selection
losses + fees**.

## The 0.01 ISK game *is* market making

EVE station trading is textbook market making with EVE’s rules. To stay at the front of the queue
(price-time priority), makers **relist by 0.01 ISK** to undercut rivals on the sell side and overcut on
the buy side — a constant micro-competition that squeezes the spread toward the floor set by **broker
and relist fees**. Those fees are the maker’s cost of doing business; the viable spread is what’s left
after them. When too many makers crowd an item, the spread collapses below the fee floor and the trade
dies — competition competing away the profit, exactly as theory predicts.

## Running it as a strategy

Professional EVE market making is a portfolio discipline:

- **Pick the right items.** You want a **healthy spread relative to fees** *and* enough **volume** that
  both sides fill before the price drifts — liquidity is the maker’s lifeblood.
- **Manage inventory.** Don’t let one item’s position balloon; cap exposure per item (a
  diversification cap), and skew quotes to mean-revert your holdings.
- **Watch adverse selection.** Widen or pull quotes around events (patches, wars) when informed flow
  spikes and your stale quotes are most likely to be picked off.
- **Account for fees and capital.** Broker + sales tax set the floor; the ISK tied up in orders has an
  opportunity cost (see *Time Value of Money*).

## In IndyOps

The **station-trade candidates** in the trade optimizer are a market-making screen: they rank in-station
flips by the **spread net of broker ×2 and sales tax**, filtered by **daily volume** and **volatility**
— precisely the "healthy spread + enough liquidity + manageable risk" the maker wants. The **Demand**
tab’s spread, depth and **order-book imbalance** are the maker’s live dashboard (imbalance hints which
way you’ll get filled and where adverse selection lurks), and the **portfolio / diversification caps**
encode the inventory discipline. Read together, they turn the 0.01 ISK grind from a chore into a
quantified liquidity-provision business.`,
  quiz: [
    { q: 'A market maker profits primarily from…', answer: 1,
      options: ['Predicting the price direction', 'Capturing the bid-ask spread by providing liquidity on both sides', 'Paying no fees', 'Holding a monopoly'] },
    { q: 'The core market-making mechanic is to…', answer: 0,
      options: ['Post a buy order at the bid and a sell order at the ask, and capture the gap', 'Only buy', 'Only sell', 'Haul between regions'] },
    { q: 'The market maker needs the price mainly to…', answer: 2,
      options: ['Rise steadily', 'Fall steadily', 'Oscillate enough that both sides get filled', 'Stay perfectly fixed forever'] },
    { q: 'Inventory risk is the danger that…', answer: 3,
      options: ['Fees are too low', 'The spread is too wide', 'Demand is elastic', 'You accumulate an unwanted position whose price can move against you before you offload it'] },
    { q: 'A maker manages inventory back to neutral by…', answer: 0,
      options: ['Skewing quotes to encourage the fills that rebalance', 'Ignoring it', 'Widening the spread to infinity', 'Hauling to another region'] },
    { q: 'Adverse selection means the maker…', answer: 1,
      options: ['Gets the best fills', 'Systematically trades against better-informed traders and loses on those fills', 'Pays no tax', 'Always profits'] },
    { q: 'A market maker is profitable only when spread captured exceeds…', answer: 2,
      options: ['Zero', 'The risk-free rate', 'Inventory losses + adverse-selection losses + fees', 'The blueprint cost'] },
    { q: 'The EVE 0.01 ISK relist game is, economically…', answer: 0,
      options: ['Market making under price-time priority, with fees as the cost of doing business', 'A monopoly', 'Pure arbitrage', 'A tax'] },
    { q: 'When too many makers crowd an item, the spread…', answer: 3,
      options: ['Widens forever', 'Becomes a tax', 'Is set by CCP', 'Collapses toward the fee floor and the trade dies (competition)'] },
    { q: 'For station trading you most want an item with…', answer: 1,
      options: ['A tiny spread and no volume', 'A healthy spread relative to fees AND enough volume to fill both sides', 'Maximum volatility and zero liquidity', 'A monopoly seller'] },
    { q: 'A maker should widen or pull quotes around patches/wars because…', answer: 2,
      options: ['Fees rise then', 'Volume disappears', 'Informed flow spikes and stale quotes get picked off (adverse selection)', 'The tax changes'] },
    { q: 'In IndyOps, the station-trade candidates rank flips by…', answer: 0,
      options: ['Spread net of broker ×2 and sales tax, filtered by volume and volatility', 'Blueprint ME', 'Distance in jumps', 'The risk-free rate'] },
  ],
}

const gameTheory = {
  key: 'game-theory',
  title: 'Game Theory in Markets',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Advanced',
  difficulty: 3,
  summary: 'Strategy when your payoff depends on what others do. Nash equilibrium, the prisoner’s dilemma, Bertrand price competition driving price to cost, why cartels are unstable — and why EVE’s 0.01 ISK undercut war is game theory you can watch live.',
  body: `# Game Theory in Markets

When there are only a few players and your best move depends on *their* moves, simple supply-and-demand
isn’t enough — you need **game theory**, the study of strategic decisions among interacting players. It
explains oligopoly pricing, why cartels collapse, and why the EVE undercut war ends exactly where it
does.

> A "game" is any situation where your payoff depends not just on your choice but on others’ choices
> too. The question is no longer "what’s best for me?" but "what’s best for me *given what they’ll
> do*?"

## The ingredients of a game

A game has **players**, **strategies** (the choices each can make), and **payoffs** (what each gets for
every combination of choices). Lay the payoffs out in a matrix and you can reason about what rational
players will do.

## Nash equilibrium

The central solution concept is the **Nash equilibrium**: a set of strategies where **no player can do
better by unilaterally changing their own choice**, given what everyone else is doing. It’s a
*self-enforcing* outcome — nobody has an incentive to deviate. A game can have one, several, or (in
mixed strategies) always at least one Nash equilibrium (John Nash’s theorem).

## The prisoner’s dilemma

The most famous game shows why rational individuals fail to cooperate even when cooperation would help
them both. Each player can **cooperate** or **defect**; defecting is individually better *whatever* the
other does, so both defect — landing on an outcome **worse for both** than mutual cooperation. The
collectively-good outcome (both cooperate) is **not** the Nash equilibrium.

[[fig:payoffMatrix|A pricing prisoner’s dilemma. Both holding price is best jointly (+3, +3), but each is tempted to undercut for a bigger share (+4, −1). Since undercutting beats holding whatever the rival does, both undercut — the Nash equilibrium (+1, +1), worse for both. This is exactly the EVE undercut war.]]

## Bertrand competition — price wars to cost

Put two sellers of an identical good in price competition and the prisoner’s dilemma plays out as a
**price war**. Each can win the whole market by **undercutting** the other by a hair. So both keep
cutting… until the price hits **marginal cost**, where neither can cut further without losing money.
This is the **Bertrand paradox**: just *two* competitors with identical products can drive the price all
the way to the competitive level (P = MC). Differentiation, capacity limits, or fees soften it — but the
pressure is relentless.

## Why cartels are unstable

A **cartel** (sellers colluding to hold a high price) is the cooperative outcome of the dilemma — and
it’s fragile for the same reason. Each member is tempted to **cheat**: secretly undercut and grab share
while others hold the line. Since cheating pays whatever the others do, cartels are inherently unstable
and tend to collapse back toward competition — unless sustained by **repeated interaction** (the threat
of future punishment can make cooperation a Nash equilibrium in a repeated game — the *folk theorem*).

## EVE: game theory you can watch

EVE markets are a live game-theory lab:

- **The 0.01 ISK undercut war** is a Bertrand price war in slow motion. Each seller undercuts by the
  minimum tick to win price-time priority; the Nash equilibrium is the price ground down to **cost +
  fees**, worse for all sellers than if they’d held — exactly the prisoner’s dilemma. **Broker/relist
  fees** are what stop it at the floor rather than at zero.
- **Market cornering / cartels** — a group buying out a region’s book and relisting high is the
  cooperative (collusive) outcome. It pays *until* someone defects (seeds cheaper orders) or outside
  sellers enter, then it unravels.
- **Repeated games** — regulars who trade an item daily implicitly play a *repeated* game; tit-for-tat
  restraint (not crashing the price) can hold a fragile cooperation that one-shot logic would break.

## In IndyOps

The toolset measures the *state* of these games. The **Demand** metrics (order count, spread, depth)
reveal how crowded — how close to the Bertrand floor — a market is: many tight orders mean the war has
already driven margins thin; a wide spread with few orders means power or a cartel that hasn’t yet been
defected on. The **station-trade and trade candidates** screen for items where the price war *hasn’t*
fully competed the margin away, and the **Prediction** signal warns when a once-fat margin is
collapsing as more players pile in — the dilemma resolving in real time.`,
  quiz: [
    { q: 'Game theory is needed (over plain supply & demand) when…', answer: 1,
      options: ['There are infinitely many sellers', 'Your best move depends on what a few other players do', 'There is no tax', 'Demand is inelastic'] },
    { q: 'A Nash equilibrium is a set of strategies where…', answer: 0,
      options: ['No player can do better by unilaterally changing their own choice', 'Everyone earns the most possible', 'The price is highest', 'Players cooperate perfectly'] },
    { q: 'In the prisoner’s dilemma, the Nash equilibrium is…', answer: 2,
      options: ['Both cooperate (the best joint outcome)', 'One cooperates, one defects', 'Both defect — worse for both than cooperating', 'Random'] },
    { q: 'In the prisoner’s dilemma, defecting is…', answer: 3,
      options: ['Never worthwhile', 'Only good if the other cooperates', 'Illegal', 'Individually better whatever the other player does'] },
    { q: 'Bertrand competition between two identical-good sellers drives the price toward…', answer: 0,
      options: ['Marginal cost (the competitive level)', 'The monopoly price', 'Infinity', 'Zero volume'] },
    { q: 'The "Bertrand paradox" is that…', answer: 1,
      options: ['Two firms collude perfectly', 'Just two competitors can push the price to the competitive level', 'Prices never change', 'Monopoly is efficient'] },
    { q: 'Cartels (colluding to hold a high price) are unstable because…', answer: 2,
      options: ['They pay no tax', 'Demand is elastic', 'Each member is tempted to secretly cheat and grab share', 'Prices are fixed by CCP'] },
    { q: 'Cooperation CAN become sustainable when the game is…', answer: 3,
      options: ['Played once', 'Anonymous', 'Banned', 'Repeated (future punishment can deter cheating — the folk theorem)'] },
    { q: 'The EVE 0.01 ISK undercut war is, in game-theory terms…', answer: 0,
      options: ['A Bertrand price war / prisoner’s dilemma among sellers', 'A monopoly', 'Pure arbitrage', 'A subsidy'] },
    { q: 'In the undercut war, what stops the price at the floor instead of zero?', answer: 1,
      options: ['A CCP cap', 'Broker/relist fees (cost + fees is the floor)', 'The blueprint ME', 'Demand elasticity'] },
    { q: 'A group buying out a region’s book and relisting high is…', answer: 2,
      options: ['Perfect competition', 'A Nash equilibrium of undercutting', 'The collusive (cartel) outcome — stable only until someone defects', 'A tax wedge'] },
    { q: 'In IndyOps, many tight orders with thin margins indicate…', answer: 0,
      options: ['The price war has already driven margins near the Bertrand floor', 'A monopoly', 'A cartel at full strength', 'Illiquidity'] },
  ],
}

const timeValue = {
  key: 'time-value-of-money',
  title: 'Time Value of Money',
  section: 'economics',
  sectionLabel: 'Market Economics',
  level: 'Intermediate → Advanced',
  difficulty: 2,
  summary: 'A unit of ISK today is worth more than the same unit tomorrow. Present and future value, discounting, net present value (NPV) and the internal rate of return (IRR), opportunity cost of capital, and why long builds and tied-up inventory carry a hidden cost.',
  body: `# Time Value of Money

A unit of ISK in your wallet **now** is worth more than the same unit a month from now — because the
ISK now can be *put to work* (traded, built, invested) and grow, while the future ISK can’t until it
arrives. The **time value of money** makes that intuition precise, and it’s the missing dimension in any
decision that plays out over *time*: long builds, held inventory, research investments.

> Money has a time stamp. Comparing cash flows at different dates without adjusting for *when* they
> happen is comparing apples to next month’s apples.

## Future value and present value

If ISK earns a return \`r\` per period, then \`X\` today grows to a **future value**
\`FV = X·(1 + r)ⁿ\` after \`n\` periods (compounding). Run it backwards to find what a future amount is
worth *today* — its **present value**:

\`PV = FV / (1 + r)ⁿ\`.

This **discounting** shrinks far-off cash flows toward zero — the later the payoff and the higher the
rate, the less it’s worth now. The rate \`r\` is your **opportunity cost of capital**: the return you
*forgo* by tying ISK up here instead of in its next-best use.

[[fig:discounting|The same future cash flow is worth progressively less the further out it lands: present value = FV/(1+r)ⁿ. Discounting (here r = 12%) is just compounding run in reverse — it converts future ISK into today’s ISK so you can compare them fairly.]]

## Net present value (NPV)

Most ventures are a *stream* of cash flows: pay out now, receive later. **Net present value** discounts
every cash flow back to today and sums them:

\`NPV = Σ CFₜ / (1 + r)ᵗ\`  (with the upfront outlay as a negative \`CF₀\`).

The decision rule is clean: **NPV > 0 → the venture earns more than your cost of capital → accept;
NPV < 0 → reject.** NPV is the single most important capital-budgeting number because it puts every
project on one comparable, time-adjusted scale.

## Internal rate of return (IRR)

The **internal rate of return** is the discount rate at which \`NPV = 0\` — the venture’s own
break-even return. Compare it to your cost of capital: **IRR > r → accept.** It’s intuitive (a "% return"
on the project), but it has traps (multiple IRRs with irregular cash flows, and it can mis-rank
mutually-exclusive projects), so NPV is the safer master rule.

[[fig:npvProfile|The NPV profile: NPV falls as the discount rate rises, crossing zero at the internal rate of return. If your cost of capital is left of the IRR, NPV is positive — accept; to the right, reject.]]

## Opportunity cost of capital — the EVE rate

What’s "r" in EVE? There’s no risk-free bond, but there *is* a very real **opportunity cost of capital**:
the return you could earn on the same ISK elsewhere — station trading, hauling, another build. If
liquid trading reliably returns a few percent per cycle, then *that* is your hurdle rate. A build that
ties up ISK for two weeks must beat what those weeks of trading would have earned — not merely show a
positive raw margin.

## Why long builds and inventory cost more than they look

The time value of money quietly taxes two common situations:

- **Long production timers.** Capital tied up in a multi-day/-week build (materials + WIP) earns nothing
  while it cooks. Its true return is the margin *discounted* over the build time and *divided* by the
  time — which is why **return-per-day** and **return-per-slot**, not raw margin, are the right ranking.
- **Held inventory.** Goods sitting unsold are ISK frozen at their cost; every day unsold is a day of
  forgone return. This is the **holding cost** — and it’s why slow-moving stock can quietly lose to a
  thinner-margin, faster-turning item.

## In IndyOps

Time value shows up wherever a decision spans time. The **Monte-Carlo profit simulator** carries a
**holding-cost / daily-rate** term and a **return-per-time** metric, so a fat-margin-but-slow build is
scored against its time honestly rather than on raw profit. The production tools surface
**return-per-slot** and **return-per-hour** precisely because a slot is scarce capital with an
opportunity cost over time. And the trade tools’ "patient vs instant" choice is a time-value trade:
accept a lower *immediate* margin (instant sell into the bid) or wait for a higher one (patient sell)
and bear the inventory holding cost in between.`,
  quiz: [
    { q: 'The time value of money says a unit of ISK today is…', answer: 1,
      options: ['Worth the same as a unit next month', 'Worth more than the same unit in the future (it can be put to work now)', 'Worth less than future ISK', 'Only valuable if invested in bonds'] },
    { q: 'Present value is computed as…', answer: 0,
      options: ['PV = FV / (1 + r)ⁿ', 'PV = FV × (1 + r)ⁿ', 'PV = FV − r', 'PV = FV × n'] },
    { q: 'Discounting a far-future cash flow makes it…', answer: 2,
      options: ['Larger', 'Unchanged', 'Smaller in present-value terms (the later and the higher r, the less it’s worth now)', 'Negative'] },
    { q: 'The discount rate r represents your…', answer: 3,
      options: ['Sales tax', 'Blueprint ME', 'Inflation only', 'Opportunity cost of capital (the return forgone elsewhere)'] },
    { q: 'Net present value (NPV) is…', answer: 0,
      options: ['The sum of all cash flows discounted to today', 'The largest single cash flow', 'Total revenue', 'The undiscounted profit'] },
    { q: 'The NPV decision rule is…', answer: 1,
      options: ['Accept if NPV < 0', 'Accept if NPV > 0 (earns more than your cost of capital)', 'Accept only if IRR = 0', 'Always accept'] },
    { q: 'The internal rate of return (IRR) is the discount rate at which…', answer: 2,
      options: ['Revenue is maximised', 'The tax is zero', 'NPV = 0 (the project’s break-even return)', 'Cost is lowest'] },
    { q: 'Using IRR, you accept a project when…', answer: 0,
      options: ['IRR > your cost of capital r', 'IRR < r', 'IRR = 0', 'NPV < 0'] },
    { q: 'Why is NPV usually the safer master rule over IRR?', answer: 3,
      options: ['It needs no discount rate', 'It ignores time', 'It is always positive', 'IRR can give multiple values and mis-rank mutually-exclusive projects'] },
    { q: 'In EVE, the relevant "r" (hurdle rate) is best thought of as…', answer: 1,
      options: ['A risk-free government bond', 'The return the same ISK could earn elsewhere (trading, hauling, another build)', 'Always zero', 'The sales-tax rate'] },
    { q: 'A long production timer is costly because…', answer: 2,
      options: ['It raises the sales tax', 'It changes the blueprint ME', 'Capital is tied up earning nothing while it builds — so rank by return-per-day, not raw margin', 'It lowers demand'] },
    { q: 'In IndyOps, the profit simulator’s holding-cost / return-per-time terms exist to…', answer: 0,
      options: ['Score a fat-margin-but-slow build honestly against the time it ties up capital', 'Compute the bid-ask spread', 'Estimate elasticity', 'Set the monopoly price'] },
  ],
}

export const ARTICLES = [
  monteCarlo, scenarios, markowitz,
  demand, demandMetrics, demandForecasting, liquidityRisk, orderBookMicrostructure,
  supply, marketEquilibrium, elasticityArt, surplus, costStructures, marginalAnalysis,
  opportunityCost, marketStructures, arbitrage, marketMaking, gameTheory, timeValue,
]

// articles grouped by section (for the sidebar)
export const SECTIONS = ARTICLES.reduce((acc, a) => {
  const s = acc.find(x => x.section === a.section)
  if (s) s.articles.push(a)
  else acc.push({ section: a.section, label: a.sectionLabel, articles: [a] })
  return acc
}, [])
