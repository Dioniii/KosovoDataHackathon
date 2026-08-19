# Known Issues

## No real multi-year trend data

**Where:** `app/scoring.py` (`housing_trend_points`, `business_trend_points`), used by the
line charts in both tabs of `app/app.py`.

**Problem:** The task spec for the app asks for "a Plotly line chart of the region's
multi-year trend" (property tab) and a "growth trend chart" (business tab). But
`docs/DATA_CONTRACT.md` doesn't define a time-series field anywhere — every metric is a
single latest value (`investment_yoy_pct`, `tourism_gap_score`, `growth_pct`,
`count_latest`), except `housing.*.index_2018_base` / `index_latest`, which is exactly
two points.

**Current workaround:** The charts show only the two real data points that can be derived
without fabricating anything:
- Property tab: the region's housing bucket (`prishtina`/`rest`) 2018 baseline index vs.
  latest index.
- Business tab: `count_latest` and a prior-period count backed out algebraically from
  `growth_pct` (`prev = count_latest / (1 + growth_pct/100)`).

Neither is a true multi-year series — it's two points connected by a line.

**To do it properly, this needs a pipeline change, not just an app change:**
1. `pipeline/fetch.py` would need to pull more than the latest-two-periods from ASKdata
   for `inv04.px` (investment), `ht03.px`/`ht02.px` (tourism), `IPBN02.px` (housing), and
   `enterprises03.px` (business) — those tables already have multi-year coverage
   (2018–2024, 2008–2025, 2018Q1–2026Q1, 2019Q1–2023Q4 respectively per the README), so
   the raw history is available upstream.
2. `docs/DATA_CONTRACT.md` would need a new field, e.g. a `history: [{period, value}]`
   array per region and per `business_sectors[].by_municipality[...]` entry.
3. `app/scoring.py`'s two trend-point helpers would be replaced by reading that array
   directly, and `app/app.py`'s trend charts would need no changes beyond that.

Flagging this rather than implementing it — check whether it's worth the pipeline/contract
change before the deadline, or whether the two-point trend is good enough for the demo.
