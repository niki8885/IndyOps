<!--
Thanks for contributing to IndyOps! Please read docs/CONTRIBUTING.md first.
Keep the title in conventional-commit style, e.g. "fix: ...", "feat: ...", "chore: ...".
-->

## Summary

<!-- What does this PR do and why? -->

## Related issues

<!-- e.g. Closes #123 -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes existing behaviour)
- [ ] Data / calculation correctness
- [ ] Refactor / tech debt
- [ ] Docs only
- [ ] CI / infra / tooling

## Areas touched

- [ ] Backend / API
- [ ] Services (pure logic)
- [ ] Adapters (I/O)
- [ ] Repositories (SDE reads)
- [ ] Chain solver / slot assignment
- [ ] Worker / collectors
- [ ] Haskell chain-engine
- [ ] Fortran analytics-engine
- [ ] Frontend
- [ ] Database / migrations
- [ ] Infra / CI-CD

## How was this tested?

<!-- Commands run and what you observed. -->

```sh
# e.g.
# pytest -q
# ruff check app tests
```

## Checklist

- [ ] Layering respected: pure logic in `services/`, I/O in `adapters/`, SDE reads in `repositories/`
- [ ] Tests added/updated and passing (`pytest -q`)
- [ ] Lint passes (`ruff check app tests`)
- [ ] If the solver changed, **Python ↔ Haskell parity** still holds (parity test passes)
- [ ] If the schema changed, an Alembic migration is included
- [ ] If `eve_*` SDE schema changed, the SDE sync was/needs to be re-run
- [ ] Docs updated (README / CONTRIBUTING / inline) where relevant
- [ ] No secrets committed (`.env`, tokens, passwords)

## Screenshots / output

<!-- For UI or behavioural changes. -->

## Additional notes

<!-- Migration steps, follow-ups, anything reviewers should know. -->
