---
name: Bug report
about: Report something that is broken or behaving incorrectly
title: "[Bug] "
labels: bug
assignees: ''
---

## Summary

<!-- A clear, concise description of what the bug is. -->

## Affected area

<!-- Tick all that apply. -->

- [ ] Backend / API (FastAPI)
- [ ] Chain solver (make-vs-buy / BOM expansion)
- [ ] Slot assignment (OR-Tools)
- [ ] Market tracking / worker collectors
- [ ] Haskell chain-engine
- [ ] Fortran analytics-engine
- [ ] Frontend (React UI)
- [ ] Database / migrations (Alembic, Timescale)
- [ ] Infra / Docker / CI-CD
- [ ] Other

## Steps to reproduce

1.
2.
3.

## Expected behaviour

<!-- What you expected to happen. -->

## Actual behaviour

<!-- What actually happened. Include exact error messages. -->

## Reproduction details

<!-- If the bug involves the chain solver or an API call, paste the request. -->

```json
// e.g. POST /api/v1/... body, or the type_id / blueprint involved
```

- **Compute engine reported** (`"engine"` field): <!-- haskell | python | n/a -->
- Relevant `type_id` / blueprint / region:

## Logs / stack trace

<details>
<summary>Logs</summary>

```
paste here
```

</details>

## Environment

- IndyOps version / commit:
- Deployment: <!-- Docker Compose | local dev | Hetzner -->
- OS:
- Browser (if frontend): 
- Python / Node / GHC version (if local dev):

## Additional context

<!-- Screenshots, related issues, anything else. -->
