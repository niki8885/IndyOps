# analytics-engine

Fortran port of the commodity-index analytics compute
(`backend/app/services/{indicators,risk,index_report}.py`). A pure numeric core
behind a thin stdin→stdout JSON shell: it reads a numeric-only request and writes
the computed `series` / `stats` / `risk` / `montecarlo` / `heatmap` / `states`.

The Python `compute_index_payload` stays as the **oracle**; this binary must match
it (`backend/tests/test_analytics_fortran_parity.py`).

This project also builds a **second binary, `profit-sim`** — a Monte-Carlo
profit simulator (IO-22) that reuses the same numeric primitives
(`rng`/`sort_stats`/`json`). See [profit-sim](#profit-sim--monte-carlo-profit-simulator)
below. The `analytics-engine` sources (indicators/risk/report/main) are untouched
by it, so its parity test is unaffected.

## Dependency-free by design

Only gfortran + a hand-rolled JSON (`src/json.f90`) — no external Fortran
libraries. Statically linked, so it ships as **one standalone binary** with no
runtime DLL dependency (`src/compat.c` supplies a `strndup` shim that static
libgfortran needs on MSYS2/UCRT64). This builds **offline** and sidesteps the TLS
interception on the dev machine. Same philosophy as the Haskell `chain-engine`.

## Wire format

The request is numeric-only — Python decodes calendar fields (weekday/hour and a
last-24h mask) so the engine never parses dates or strings:

```json
{ "window": 10,
  "price": [..], "volume": [..],            // null → NaN
  "last24_mask": [0|1,..], "weekday": [..], "hour": [..],
  "liquidity_last": .., "entropy_last": .., "top3_share_last": ..,
  "mc": { "horizon": 24, "n_paths": 500, "seed": 42 } }
```

The adapter re-attaches the pass-through fields (`key/label/kind/window/
timestamps/price/volume`) it already holds, producing the exact oracle payload.

## Numerical fidelity

The deterministic metrics replicate pandas/numpy to floating-point round-off
(parity test asserts `rel_tol=1e-7`; observed agreement is ~1e-12 or exact):

* `.std()` is **ddof=1** (pandas sample std) for indicators/volatility, but
  **ddof=0** (`np.std`) for the Monte-Carlo sigma — both call sites honoured.
* `np.percentile` uses **linear interpolation** on sorted data (VaR, regime
  thresholds, MC bands).
* RSI is the **simple-MA** variant; division-by-zero is left to IEEE (down=0 →
  +inf → rsi=100), reproducing pandas without special cases.
* `np.histogram` indexing incl. its float edge corrections.

**Monte-Carlo is statistical, not bit-exact.** The engine uses xoshiro256** +
Box–Muller (`src/rng.f90`), not numpy's PCG64 + Ziggurat: matching a particular
pseudo-random stream is impossible across implementations and is not a meaningful
measure of MC accuracy. With identical mu/sigma the percentile bands converge to
the same log-normal quantiles (observed gap < 2%), which is what the parity test
checks.

## Build

```sh
sh build.sh                      # POSIX (Linux/macOS)
powershell -File build.ps1       # Windows (MSYS2/UCRT64 gfortran)
```

`bin/` and `build/` are git-ignored — the binary is platform-specific and rebuilt
per host. Smoke test:

```sh
./bin/analytics-engine < sample-request.json
```

## How Python finds it

`backend/app/adapters/analytics_engine.py` looks for the binary at
`$ANALYTICS_ENGINE_BIN`, else `fortran/analytics-engine/bin/analytics-engine[.exe]`.
If it is missing or errors, the adapter **falls back to the Python oracle**, so
the app works either way. The `/analysis/index/{key}` response reports which
engine ran (`"engine": "fortran" | "python"`).

## Production (Docker / Hetzner)

Wired into `backend/Dockerfile`: a `debian:bookworm-slim` builder stage installs
gfortran and runs `build.sh`, then the final image `COPY`s the Linux binary to
`/usr/local/bin/analytics-engine`, installs `libgfortran5` for the runtime, and
sets `ANALYTICS_ENGINE_BIN`. The deploy workflow additionally builds the engine
and runs the parity test, so a logic regression blocks the deploy. `bin/` +
`build/` stay git-ignored — the committed sources are compiled fresh per image.

## profit-sim — Monte-Carlo profit simulator

A second binary built from this project (`src/distrib.f90`, `src/montecarlo.f90`,
`app/profitsim.f90`) that estimates **risk-adjusted manufacturing profitability
under market uncertainty**. It wraps the deterministic profit calc
(`services.chain.ChainPlan` / `services.manufacturing.CalcResult`) in a sampling
model and reduces thousands of scenarios to metrics (E[Profit], VaR 5%/1%,
CVaR/worst-1%, σ, CV, P(loss), percentiles, time).

Same architecture as `analytics-engine`: a pure stdin→stdout JSON filter with a
Python **oracle** (`backend/app/services/profit_sim.py`) and adapter
(`backend/app/adapters/profit_sim.py`, prefers the binary via `PROFIT_SIM_BIN`,
else falls back to Python). Parity is **statistical** (own RNG ≠ numpy) —
`backend/tests/test_profit_sim_fortran_parity.py`.

Model per scenario `k` (`j` over buy-legs + the product):

```
z      ~ correlated N(0,1)        (corr_mode 0: Cholesky L·ε | 1: factor loadings·F + idio·η)
price_j = qgrid_j(Φ(z_j))         (dist_mode 0: empirical copula) | exp(mu_j+sigma_j·z_j) (1)
fill_j  = min(1, participation_cap·volume_j·horizon / qty_j)
profit  = product_qty·sell·fill − taxes − Σ acquire_j·qty_j·(1+(1−fill_j)·premium) − fixed − logistics
```

The request is **numeric-only and rectangular** — Python reduces history to
`mu`/`sigma` + a 101-point quantile grid and pre-builds the Cholesky factor and
factor loadings; every 2-D array (`qgrid`, `l`, `loadings`) is **flattened
row-major** because `src/json.f90` reads only flat arrays. The response keys
mirror `services.profit_sim.SimMetrics`. Smoke test:

```sh
./bin/profit-sim < sample-profitsim.json
```
