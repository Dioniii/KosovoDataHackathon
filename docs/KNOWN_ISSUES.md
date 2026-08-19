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

---

## Worth implementing (not a bug): scheduled data refresh via GitHub Actions

**Where:** `pipeline/fetch.py`, plus a new `.github/workflows/` file. Relevant once the app is
deployed on Streamlit Community Cloud.

**Why it's worth doing:** `pipeline/fetch.py` only runs when someone runs it by hand.
`pipeline/data.json` is a static file committed to the repo, and the app is designed to only
ever read that committed file — it never calls ASKdata or World Bank itself. That split is
correct (it's what keeps a flaky ASKdata response from ever blocking a real user's page load),
but nothing currently keeps `data.json` fresh after the hackathon — the snapshot goes stale the
moment people stop re-running the pipeline manually.

**Proposed approach:** a scheduled GitHub Actions workflow
(`.github/workflows/refresh-data.yml`) that:
1. Triggers on a `schedule:` cron (e.g. hourly or daily) plus `workflow_dispatch` for manual runs.
2. Checks out the repo on a fresh runner, installs Python + `requests`.
3. Runs `python pipeline/fetch.py`.
4. Commits and pushes `pipeline/data.json` if it changed, using the built-in `GITHUB_TOKEN`
   (no extra secrets needed — neither ASKdata nor World Bank require auth).

Streamlit Community Cloud auto-redeploys on new commits to the connected branch, so this keeps
the live app's data current on a schedule without adding a live API call to the request path.

**Alternatives considered and rejected:**
- Calling `fetch.py` directly from the Streamlit app (even behind `st.cache_data(ttl=...)`)
  still risks a slow/flaky ASKdata call blocking a real page load on cache expiry.
- Databricks Jobs — cluster spin-up time/cost is overkill for a handful of lightweight REST
  calls, and it has no native "commit back to GitHub" step the way GitHub Actions does.

**Status:** not implemented. Worth doing if the demo needs to stay current over multiple days;
skip it if this is a one-shot hackathon demo where the pipeline is just re-run manually before
presenting.
