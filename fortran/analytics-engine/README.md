# analytics-engine

Fortran port of the commodity-index analytics compute
(`backend/app/services/{indicators,risk,index_report}.py`). A pure numeric core
behind a thin stdin→stdout JSON shell: it reads a numeric-only request and writes
the computed `series` / `stats` / `risk` / `montecarlo` / `heatmap` / `states`.

The Python `compute_index_payload` stays as the **oracle**; this binary must match
it (`backend/tests/test_analytics_fortran_parity.py`).

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
