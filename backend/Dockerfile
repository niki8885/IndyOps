# Build context is the repo root

# stage 1: compile the Haskell chain-engine (offline, boot libs only)
FROM haskell:9.6.6 AS chain-builder
WORKDIR /build
COPY haskell/chain-engine/src/ ./src/
COPY haskell/chain-engine/app/ ./app/
RUN mkdir -p /out \
 && ghc -O2 -isrc -iapp -outputdir /tmp/obj app/Main.hs -o /out/chain-engine

# stage 1b: compile the Haskell risk-engine (offline, boot libs only) ──────
FROM haskell:9.6.6 AS risk-builder
WORKDIR /build
COPY haskell/risk-engine/src/ ./src/
COPY haskell/risk-engine/app/ ./app/
RUN mkdir -p /out \
 && ghc -O2 -isrc -iapp -outputdir /tmp/obj app/Main.hs -o /out/risk-engine

# stage 2: compile the Fortran analytics-engine + profit-sim (gfortran only) ─
FROM debian:bookworm-slim AS analytics-builder
WORKDIR /build
RUN apt-get update \
 && apt-get install -y --no-install-recommends gfortran \
 && rm -rf /var/lib/apt/lists/*
COPY fortran/analytics-engine/ ./analytics-engine/
RUN sh analytics-engine/build.sh

# stage 3: python backend
FROM python:3.12-slim
WORKDIR /app

# Native-engine runtime libs: libgmp10 for GHC's Integer (chain-engine),
# libgfortran5 for the gfortran-built analytics-engine.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgmp10 libgfortran5 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ app/
COPY backend/alembic.ini .
COPY backend/migrations/ migrations/

# Native make-vs-buy engine. The adapter prefers it via CHAIN_ENGINE_BIN and
# falls back to the pure-Python core if it is ever missing.
COPY --from=chain-builder /out/chain-engine /usr/local/bin/chain-engine
ENV CHAIN_ENGINE_BIN=/usr/local/bin/chain-engine

# Native analytics engine (indicators / risk / Monte-Carlo). Same fallback
# contract: the adapter prefers it via ANALYTICS_ENGINE_BIN, else pure Python.
COPY --from=analytics-builder /build/analytics-engine/bin/analytics-engine /usr/local/bin/analytics-engine
ENV ANALYTICS_ENGINE_BIN=/usr/local/bin/analytics-engine

# Native Monte-Carlo profit simulator (IO-22), built from the same Fortran project.
COPY --from=analytics-builder /build/analytics-engine/bin/profit-sim /usr/local/bin/profit-sim
ENV PROFIT_SIM_BIN=/usr/local/bin/profit-sim

# Native Scenario Simulation engine (IO-23), built from the same Fortran project.
COPY --from=analytics-builder /build/analytics-engine/bin/scenario-sim /usr/local/bin/scenario-sim
ENV SCENARIO_SIM_BIN=/usr/local/bin/scenario-sim

# Native risk-scoring / strategy-ranking engine (Haskell). Falls back to Python.
COPY --from=risk-builder /out/risk-engine /usr/local/bin/risk-engine
ENV RISK_ENGINE_BIN=/usr/local/bin/risk-engine

EXPOSE 8000

# Apply migrations
CMD ["sh", "-c", "python -m app.migrate; uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=*"]
