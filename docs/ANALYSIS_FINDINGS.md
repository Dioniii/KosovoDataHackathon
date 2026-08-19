# Analysis Findings — data review before scoring/insights

Review of `pipeline/data.json` (real data from `fetch.py`) against
`docs/DATA_CONTRACT.md`, done before implementing scoring and insight text.
The contract shape is stable and correct — these are **content** issues in the
numbers, not schema issues. Everything scoring/insights-related is written
defensively around them.

## Repo status at time of review
- **Pipeline (fetch.py):** complete and solid — real data from all 5 ASKdata
  tables + World Bank, with disk cache, retry-and-fallback, atomic writes, and
  a region-alias map handling ASKdata's inconsistent spellings.
- **`app/`:** empty except `.gitkeep` — no scoring functions, no Streamlit app yet.
- **`insights`:** all 121 entries are empty strings — not started.

## Issue 1 — Business-sector growth is dominated by tiny-base noise (highest priority)
Growth ranges are extreme because most municipalities have almost no businesses
in these sectors:
- Accommodation & food (I): **24 of 38** municipalities have ≤3 units.
- Real estate (L): **33 of 38** have ≤3 units.
- Top raw "growth" results are things like Mitrovica Veriore 1→9 units (+800%),
  Lipjan 2→5 (+150%) — statistical noise, not real hubs.

**Consequence:** `business_score` normalized on raw `growth_pct` ranks noise at
the top. **Mitigation implemented:** a minimum-count floor (`MIN_COUNT`, default
15) — municipalities below it are scored but flagged `low_confidence` and pushed
below any qualifying municipality, so a real hub never loses to a 1→3 blip.

## Issue 2 — `investment_yoy_pct` is a proxy, not investment growth
`inv04.px` reports investment *composition* (category shares summing to 100%),
not investment levels, so there is no total to grow. `fetch.py` substitutes the
year-over-year change in the **construction category's share** (documented in a
code comment). It is negative for almost every region (Prishtinë −14.5,
Gjilan −25.6).

**Consequence:** insight text must NOT say "investment fell X% in region Y" —
the number is the shift in construction's slice of the investment mix.
**Mitigation implemented:** insight text describes it as
"construction's share of the investment mix," never "investment growth," and the
disclaimer sentence covers the proxy explicitly.

## Issue 3 — Housing premise isn't supported by the index
The property path assumes Prishtina is the premium/expensive bucket. The HPI
shows Prishtina **130.0** vs. rest **130.6** — nearly identical, and "rest" is
slightly higher. The index measures price *growth since 2018 (2018=100)*, not
price *level*, so it cannot establish that Prishtina is more expensive.

**Consequence:** a "budget threshold excludes Prishtina" rule rests on an
assumption the data can't back. **Flagged to the frontend teammate** — belongs in
the app layer, not scoring. Insight text speaks only to price *growth*, never level.

## Issue 4 — minor: FDI is exactly 10.0
`national.fdi_pct_gdp = 10.0` is suspiciously round. Worth a 10-second check that
it's a real World Bank observation and not a rounded/fallback value. No code impact.

## Function signatures (agree with frontend teammate)
Implemented in `app/scoring.py`, snake_case mirroring the frontend's camelCase:
- `momentum_score(regions, w_investment=0.5, w_tourism=0.5) -> {name: 0..100}` — weights are user-adjustable inputs, not constants.
- `proximity_weight(distance_km) -> float` = `1 / (1 + distance_km / 50)`.
- `haversine_km(lat1, lon1, lat2, lon2) -> float`.
- `business_score(sector, regions, min_count=15) -> {muni: {score, low_confidence, ...}}`.
