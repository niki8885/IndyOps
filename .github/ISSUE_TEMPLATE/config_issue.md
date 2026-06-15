---
name: Configuration / setup issue
about: Trouble installing, configuring, building, or deploying IndyOps
title: "[Setup] "
labels: setup
assignees: ''
---

## What are you trying to do?

<!-- e.g. run with Docker Compose, set up local dev, build the Haskell engine, deploy to Hetzner. -->

## What goes wrong?

<!-- Describe the failure. Include exact error output. -->

## Setup path

- [ ] Docker Compose (`docker compose up`)
- [ ] Local backend (uvicorn + venv)
- [ ] Local frontend (Vite / npm)
- [ ] Database / Alembic migrations
- [ ] Haskell chain-engine build
- [ ] Fortran analytics-engine build
- [ ] CI / GitHub Actions
- [ ] Deployment (GHCR / Hetzner)
- [ ] Other

## Steps taken

1.
2.
3.

## Error output

<details>
<summary>Output / logs</summary>

```
paste here
```

</details>

## Environment

- IndyOps version / commit:
- OS:
- Docker / Docker Compose version:
- Python version:
- Node version:
- PostgreSQL version:
- GHC version (if building Haskell):

## Configuration

<!-- Relevant .env keys WITHOUT secret values (do NOT paste POSTGRES_PASSWORD or SECRET_KEY). -->

```
# e.g. which vars you set, defaults vs custom
```

## Additional context

<!-- Anything else that might help reproduce the setup. -->
