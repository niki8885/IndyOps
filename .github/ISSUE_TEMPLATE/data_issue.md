---
name: Data / calculation issue
about: Report wrong numbers — incorrect costs, BOM, market data, or SDE values
title: "[Data] "
labels: data
assignees: ''
---

## What is wrong?

<!-- Describe the incorrect result: a cost, quantity, BOM node, market price, or SDE value. -->

## Type of data issue

- [ ] Make-vs-buy decision is wrong (build vs buy chosen incorrectly)
- [ ] Cost / price figure is wrong
- [ ] Bill of materials is incomplete or incorrect
- [ ] Quantities (runs, ME/TE, batch math) are wrong
- [ ] Market data is stale, missing, or implausible
- [ ] SDE values look incorrect (names, blueprints, activities)
- [ ] Other

## Affected item

- **type_id / name:**
- **Blueprint (if applicable):**
- **Activity:** <!-- manufacturing (1) / reaction (11) / other -->
- **Region / market (if market-related):**
- **ME / TE / runs used:**

## Expected value

<!-- What the number should be, and your source (in-game, third-party tool, manual calc). -->

## Actual value

<!-- What IndyOps returned. -->

## Request / response

```json
// API request and the relevant part of the response, including the "engine" field
```

- **Compute engine reported:** <!-- haskell | python -->

## Additional context

<!-- Note if you suspect a parity mismatch between the Python and Haskell engines,
     or whether re-running the SDE sync might be relevant. -->
