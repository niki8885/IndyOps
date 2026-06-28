# Contributing to IndyOps

Thanks for taking the time to contribute! This document covers the workflow, code standards, and review process.

## Table of contents

- [Getting started](#getting-started)
- [How to contribute](#how-to-contribute)
- [Development setup](#development-setup)
- [Code standards](#code-standards)
- [Testing](#testing)
- [Pull request process](#pull-request-process)
- [Reporting bugs](#reporting-bugs)
- [Security issues](#security-issues)

---

## Getting started

1. Fork the repository and clone your fork.
2. Set up your local environment (see [Development setup](#development-setup)).
3. Create a feature branch off `master`:
   ```sh
   git checkout -b feat/your-feature-name
   ```
4. Make your changes, add tests where relevant, and open a pull request.

If you plan a large change, open an issue first to discuss the approach — it avoids wasted effort.

---

## How to contribute

| Type | What to do |
|------|------------|
| Bug fix | Open an issue with the bug report template, then submit a PR |
| New feature | Open an issue to discuss scope, then submit a PR |
| Docs | PR directly — no issue needed |
| Refactor / cleanup | Open an issue first for alignment |
| Security vulnerability | See [Security issues](#security-issues) — **do not open a public issue** |

---

## Development setup

### Prerequisites

- Python 3.11 or 3.12
- Node 20+
- PostgreSQL 16 (with TimescaleDB extension)
- Docker + Docker Compose (optional, simplest path)
- GHC 9.6 (optional — only needed to build the Haskell engine)

### Quickstart with Docker Compose

```sh
cp .env.example .env      # fill in POSTGRES_PASSWORD and SECRET_KEY
docker compose up -d
```

### Manual setup

**Backend**

```sh
cd backend
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend**

```sh
cd frontend/indyops-ui
npm install
npm run dev
```

**Haskell chain-engine** (optional)

```sh
cd haskell/chain-engine
ghc -O2 -isrc -iapp -outputdir build app/Main.hs -o bin/chain-engine
# Reaction Planner batch engine (second executable over the same library):
ghc -O2 -isrc -iapp-planner -outputdir build-planner app-planner/Main.hs -o bin/reaction-planner
```

---

## Code standards

### Python

- Formatter: **Ruff** (`ruff format`). Line length 88.
- Linter: **Ruff** (`ruff check`). Fix all warnings before committing.
- Type hints required on all public function signatures.
- Follow the layering rules:
  - `services/` — pure logic, no I/O, no ORM, no HTTP.
  - `adapters/` — all subprocess, HTTP, and ORM writes.
  - `repositories/` — SDE reads only.

### JavaScript / React

- Prefer function components and hooks.
- No `console.log` left in committed code.

### Haskell

- `hlint` should report no warnings.
- Keep the chain engine a drop-in replacement: JSON schema in/out must stay compatible with the Python oracle.

### General

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`
- Keep PRs focused — one logical change per PR.
- Do not commit secrets, `.env` files, or generated build artefacts.

---

## Testing

```sh
cd backend
pytest -q              # run all tests with coverage
ruff check app tests   # lint check
```

CI runs:

- Python unit + integration tests
- Ruff lint
- Haskell build + cross-language parity test (Python oracle vs native binary)

New features should ship with tests. Bug fixes should include a regression test that fails before the fix and passes after.

---

## Pull request process

1. Ensure all CI checks pass.
2. Fill in the PR template — describe *what* changed and *why*.
3. Reference any related issue with `Closes #<number>`.
4. Request a review; address feedback before merging.
5. Squash-merge into `master` — keep history clean.

PRs that change the Haskell engine **must** keep the parity test green. If you change the JSON schema, update both sides.

---

## Reporting bugs

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). Include:

- Steps to reproduce
- Expected vs actual behaviour
- IndyOps version / commit hash
- Relevant logs or screenshots

---

## Security issues

**Do not open a public GitHub issue for security vulnerabilities.**

Please follow the process described in [SECURITY.md](SECURITY.md).
