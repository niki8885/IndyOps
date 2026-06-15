# chain-engine

Haskell port of the recursive **make-vs-buy** core (`backend/app/services/chain.py`).
Pure solver behind a thin stdin→stdout JSON shell: it reads a `ChainRequest` and
writes a `ChainPlan` in the exact same wire format the Python side uses
(`chain.to_request_dict` / `chain.plan_from_dict`).

The Python `solve_chain` stays as the oracle; this binary must match it
**exactly** — `backend/tests/test_chain_haskell_parity.py` asserts strict equality.

## Exact arithmetic

Both cores run on exact rationals (`Rational` here, `Fraction` in Python) with no
rounding, so a deep build tree carries no accumulated error. Inputs are decimal
JSON numbers parsed to exact rationals (`Json.decRational`: "0.958" → 479/500, not
a `Double`); computed money is emitted as `[numerator, denominator]` pairs. That is
what makes parity strict equality rather than a float epsilon.

## Dependency-free by design

Only GHC **boot libraries** (`base`, `containers`, `mtl`) plus a hand-rolled JSON
(`src/Json.hs`). No Hackage packages → builds **offline**, ships as one static-ish
binary. (This also sidesteps the TLS interception on the dev machine that breaks
`cabal update` / `pip`.)

## Build

Direct with GHC (no cabal/network needed):

```sh
cd haskell/chain-engine
ghc -O2 -isrc -iapp -outputdir build app/Main.hs -o bin/chain-engine      # add .exe on Windows
```

Or with cabal:

```sh
cabal build           # binary under dist-newstyle/
```

Smoke test:

```sh
./bin/chain-engine < sample-request.json
```

`bin/` and `build/` are git-ignored — the binary is platform-specific and rebuilt
per host.

## How Python finds it

`backend/app/adapters/chain_engine.py` looks for the binary at
`$CHAIN_ENGINE_BIN`, else `haskell/chain-engine/bin/chain-engine[.exe]`. If it is
missing or errors, the adapter **falls back to the Python core**, so the app works
either way. The `/manufacturing/calculate-chain` response reports which engine ran
(`"engine": "haskell" | "python"`).

## Production (Docker / Hetzner)

The binary is not committed, so a fresh image has no native engine and silently
uses the Python fallback. To run Haskell in prod, add a multi-stage build to the
backend image — compile here with a `haskell:9.6` builder stage and `COPY` the
resulting Linux binary to `haskell/chain-engine/bin/chain-engine` in the final
image (or set `CHAIN_ENGINE_BIN`). Not wired into the Dockerfile/CI yet.
