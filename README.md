# IndyOps

<!-- Status & quality -->
[![CI](https://github.com/niki8885/IndyOps/actions/workflows/ci.yml/badge.svg)](https://github.com/niki8885/IndyOps/actions/workflows/ci.yml)
[![Build & Deploy](https://github.com/niki8885/IndyOps/actions/workflows/deploy.yml/badge.svg)](https://github.com/niki8885/IndyOps/actions/workflows/deploy.yml)
[![codecov](https://codecov.io/github/niki8885/IndyOps/graph/badge.svg?token=ZJDDH8YVF0)](https://codecov.io/github/niki8885/IndyOps)
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=niki8885_IndyOps&metric=alert_status&token=5780a813124a5110da6d41d6c718437274249b6a)](https://sonarcloud.io/summary/new_code?id=niki8885_IndyOps)
[![Maintainability](https://qlty.sh/badges/95744637-29fb-4b5c-af7d-c07dc9a59a13/maintainability.svg)](https://qlty.sh/gh/niki8885/projects/IndyOps)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE.md)

<!-- Tech stack -->
![Python](https://img.shields.io/badge/Python-3.11%20|%203.12-3670A0?style=flat-square&logo=python&logoColor=ffdd54)
![JavaScript](https://img.shields.io/badge/JavaScript-ES2022-323330?style=flat-square&logo=javascript&logoColor=F7DF1E)
![Haskell](https://img.shields.io/badge/Haskell-9.4%20|%209.6%20|%209.8-5e5086?style=flat-square&logo=haskell&logoColor=white)
![Fortran](https://img.shields.io/badge/Fortran-90%20|%2095%20|%202003-734F96?style=flat-square&logo=fortran&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-5%20|%206-646CFF?style=flat-square&logo=vite&logoColor=white)

**IndyOps** is an industry-operations platform for [EVE Online](https://www.eveonline.com/).
It turns the game's published Static Data Export (SDE) and live market data into
practical manufacturing decisions: recursive **make-vs-buy** cost analysis, bill-of-materials
expansion across manufacturing **and reactions**, multi-structure production-slot assignment,
inventory and facility management, and market-price tracking.

> ⚠️ Unofficial, fan-made tool. Not affiliated with or endorsed by CCP hf. See [License](#license).

## Features

- **Make-vs-buy chain solver** — recursively expands a blueprint's whole build tree, spanning
  manufacturing **and reactions** (capital → components → reactions), and decides at every node
  whether it is cheaper to build or to buy, using exact rational arithmetic (no float drift) —
  matched bit-for-bit by the Haskell engine.
- **Multi-structure slot assignment** — assigns the chosen jobs to industry slots across one or
  more structures, under each window's slot limit (OR-Tools / CP-SAT), bouncing any overflow back
  to buy.
- **Market tracking** — background collectors snapshot prices and market indices into TimescaleDB hypertables.
- **Projects, inventory & facilities** — organise industry work across organisations.
- **REST API** — FastAPI with interactive docs at `/docs`.
- **Polyglot compute** — a Haskell engine mirrors the Python solver for speed and a Fortran engine handles analytics.

## Architecture

```
                 ┌─────────────┐
   Browser  ───► │  Frontend   │  React 19 + Vite + Plotly (nginx)
                 └──────┬──────┘
                        │ /api/v1
                 ┌──────▼──────┐
                 │   Backend   │  FastAPI (Python 3.12)
                 │             │──► Haskell chain-engine (make-vs-buy, exact rationals)
                 │             │──► Fortran analytics-engine
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐      ┌──────────────┐
                 │ PostgreSQL  │ ◄─── │   Worker     │  background collectors
                 │ (Timescale) │      │ (indices /   │  (separate container)
                 └─────────────┘      │  tracking /  │
                                      │  SDE sync)   │
                                      └──────────────┘
```

The backend follows a layered design: pure logic lives in `services/`, all I/O
(subprocess, HTTP, ORM writes) in `adapters/`, and SDE reads in `repositories/`.
Both native engines are optional accelerators — if a binary is missing the
adapter transparently falls back to the Python core, and the API reports which
engine ran (`"engine": "haskell"|"fortran"|"python"`). The Docker image compiles
both in builder stages and ships them, so production runs native.

## Tech stack

| Layer       | Technology |
|-------------|------------|
| Frontend    | React 19, React Router, Vite, Plotly |
| Backend     | FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, OR-Tools |
| Compute     | Haskell (GHC 9.6, boot libraries only), Fortran |
| Database    | PostgreSQL 16 + TimescaleDB |
| Infra       | Docker Compose, GitHub Actions → GHCR → Hetzner |

## Project structure

```
backend/    FastAPI app (api/ services/ adapters/ repositories/ core/ tasks/), migrations, tests
frontend/   React + Vite UI (indyops-ui) and nginx config
haskell/    chain-engine — Haskell port of the make-vs-buy core
fortran/    analytics-engine
docs/        CONTRIBUTING and SECURITY policy
.github/    CI/CD workflows, issue & PR templates
```

## Getting started

### Prerequisites

- Docker + Docker Compose (recommended), **or** for local dev:
  Python 3.12, Node 20+, PostgreSQL 16, and (optionally) GHC 9.6.

### Run with Docker Compose

```sh
cp .env.example .env   # set POSTGRES_PASSWORD and SECRET_KEY
docker compose up -d
```

The UI is served on `http://localhost` (port 80) and the API behind it at `/api/v1`.

### Local development

**Backend**

```sh
cd backend
python -m venv .venv && . .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

API docs: `http://localhost:8000/docs`.

**Frontend**

```sh
cd frontend/indyops-ui
npm install
npm run dev
```

**Haskell chain-engine** (optional accelerator)

```sh
cd haskell/chain-engine
ghc -O2 -isrc -iapp -outputdir build app/Main.hs -o bin/chain-engine   # add .exe on Windows
./bin/chain-engine < sample-request.json
```

See [haskell/chain-engine/README.md](haskell/chain-engine/README.md) for details.

**Fortran analytics-engine** (optional accelerator)

```sh
cd fortran/analytics-engine
sh build.sh                            # or  powershell -File build.ps1  on Windows
./bin/analytics-engine < sample-request.json
```

See [fortran/analytics-engine/README.md](fortran/analytics-engine/README.md) for details.

## Testing

```sh
cd backend
pytest -q                 # unit tests + coverage
ruff check app tests      # lint (pyflakes + syntax)
```

CI additionally builds both native engines and runs **cross-language parity** tests
against the Python oracle: strict equality for the Haskell chain-engine, and
float-tolerance / statistical agreement for the Fortran analytics-engine.

## Contributing

Contributions are welcome — please read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)
and the [Code of Conduct](CODE_OF_CONDUCT.md) first. To report a security issue, see
the [Security Policy](docs/SECURITY.md).

If this project saved you some ISK, feel free to buy me a coffee:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/Z8Z01TOFUW)

## License

This project and the code contained within this repo are licensed under the
**GNU Affero General Public License v3.0** — see [LICENSE.md](LICENSE.md).

EVE Online is owned by [CCP hf.](https://www.ccpgames.com/):

- [Third-Party Developer License Agreement](https://developers.eveonline.com/license-agreement)
- [End-user License Agreement](https://community.eveonline.com/support/policies/eve-eula-en/)

See [LICENSE-CCP.md](LICENSE-CCP.md) for CCP's trademark and intellectual-property notice.
