# Known Issues

## No real multi-year trend data (business tab only)

**Where:** `app/scoring.py` (`business_trend_points`), used by the business tab's line
chart in `app/app.py`.

**Problem:** `docs/DATA_CONTRACT.md` doesn't define a time-series field for business
registrations — `business_sectors[].by_municipality[...]` is a single latest value
(`count_latest`, `growth_pct`).

**Current workaround:** The business-tab chart shows only two points: `count_latest` and
a prior-period count backed out algebraically from `growth_pct`
(`prev = count_latest / (1 + growth_pct/100)`). Not a true multi-year series.

**Resolved for housing:** the property tab no longer has this problem — `pipeline/fetch.py`
now pulls the full quarterly series from `IPBN02.px` into `housing[bucket].history`, and
`app/forecast.py` fits a trend to it. The property tab shows that as a plain-language
urgency note ("prices projected to rise/fall X% over the next year") rather than a chart,
by product decision, not a data limitation.

**To fix the business tab the same way:** `pipeline/fetch.py` would need to pull more than
the latest-two-periods from `enterprises03.px` (2019Q1–2023Q4 per the README, so the raw
history is available upstream), and `docs/DATA_CONTRACT.md` would need a `history` array
per `business_sectors[].by_municipality[...]` entry, mirroring what housing already has.

## QA pass (Design, QA & Pitch)

Ran `app/app.py` against `pipeline/sample_data.json` and `pipeline/data.json` both
programmatically (via `streamlit.testing.v1.AppTest`, scripting every widget interaction)
and manually (`streamlit run app/app.py`, clicked through both tabs). Design-system items
(theme in `.streamlit/config.toml`, rank-color ramp, `st.metric` usage, transparent Plotly
backgrounds, disclaimer banner rendering unconditionally on load) all already match the
spec — no changes needed there.

### Passed

- Default load, both tabs: no exceptions.
- Budget tier "Under a threshold" excludes Prishtinë (`housing_bucket == "prishtina"`)
  entirely from the property ranking (list drops from 7 rows to 6), not just re-ordered.
- Momentum/tourism weight sliders swept including both-zero and both-max: no crash
  (`momentum_score` returns `0.0` cleanly when both weights are 0).
- Business-tab sector selectbox cycles through all 3 sectors with correctly different
  municipality rankings each time.
- `streamlit run app/app.py` works whether launched from the repo root or from inside
  `app/` — `data_loader.py`'s `Path(__file__)`-relative resolution makes it cwd-independent,
  confirmed by actually starting the server from both locations.
- A fresh restart of the process shows no dependence on leftover session state.

### Found: stale row-selection follows table *position*, not the selected region/municipality

**Where:** `select_row()` in `app/app.py` (used by both tabs' ranked tables).

**Repro (verified via `AppTest`, both tabs):**
1. Property tab: select a row other than the top one (e.g. row 3, "Gjakovë" while every
   weight/anchor is default).
2. Change *any* control that re-sorts the list without changing its row count — e.g. the
   anchor-point selectbox, or either weight slider.
3. The detail panel silently now shows a *different* region (in one repro run: "Pejë")
   with no new click from the user.

Same pattern on the business tab: select a row (e.g. row 2 → "Viti" under sector I), switch
the sector dropdown to a different sector (still ~38 rows), and the detail panel silently
shows whatever municipality now occupies row 2 in the new sector's ranking (in one repro
run: "F.Kosovë" under sector L) — a municipality the user never clicked on.

**Why it happens:** Streamlit's `on_select="rerun"` dataframe selection is stored by
*integer row position*, not by the row's identity. `select_row()` reads `rows[0]` from the
selection event and indexes back into the (freshly re-sorted or newly-filtered) dataframe
with `df.iloc[row]`. When a control changes the row *count* (e.g. property tab's budget-tier
exclusion, 7→6 rows), Streamlit correctly detects the selection index is now out of range
and resets it to the top row — that path is fine, verified working. But when a control only
changes row *order or content* while keeping the same row count (anchor switch, slider
tweak, sector switch), Streamlit has no way to know the old position no longer means the
same thing, so the stale index silently re-attaches to whatever is now in that slot. The
highlighted row and the detail panel do stay in sync with *each other* — this isn't a
crash or a desync between the table and the panel — but the tool silently swaps which
region/municipality the user is looking at without them clicking anything, which is a real
trust problem for a tool whose whole pitch is "every ranking is honestly grounded in real
numbers."

**Suggested fix (not applied — logic change in `app.py`, flagging per the "don't fix
someone else's code out from under them" rule rather than patching it):** track the
selected *name* in `st.session_state` (e.g. `st.session_state[f"{key}_selected_name"]`)
instead of relying solely on row position; on rerun, if that name still exists in the new
ranking, keep showing it regardless of its new row position; if it doesn't, only then fall
back to the top row. This needs the app developer's call on whether it's worth doing before
the deadline — the current behavior never crashes, it's a silent-mislabel risk, not a
blocker.

### Not independently verified (needs a live human pass, not just scripted checks)

- Visual contrast of the lightest rank-ramp color (`#86b6ef`) against the page background
  (`#fcfcfb`) at actual screen brightness.
- Whether the 38-row business-tab chart/table looks cramped on a real screen.
- Browser window resize / narrow-viewport behavior (wide layout).
- Albanian diacritics (ë, ç) rendering correctly in the browser — the underlying JSON is
  correct UTF-8 (`ensure_ascii=False` in `fetch.py`), and this is expected to be fine, but a
  human should actually look at the rendered page once before the demo rather than take
  that on faith.
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




## LLM integration
## Page Translation
## Implement Cache
## Prediction Model (Regression) - Add urgency if doesnt invest by 2027 margins arise by 20%
skip it if this is a one-shot hackathon demo where the pipeline is just re-run manually before
presenting.
