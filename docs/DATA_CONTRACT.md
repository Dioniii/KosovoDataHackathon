# Data Contract

This document defines the exact JSON shape that `pipeline/fetch.py` produces
(`pipeline/data.json`) and that `pipeline/sample_data.json` mocks for local
development. Every other part of this project (the app, insight briefs) reads
and writes against this shape. If you need to change a field name, update this
file first and tell the team.

## Top-level shape

```jsonc
{
  "national": {
    "gdp_growth_pct": number,          // latest annual GDP growth, %
    "fdi_pct_gdp": number,             // latest FDI inflows as % of GDP
    "last_updated": "YYYY-MM-DD"
  },

  "regions": [
    {
      "name": string,                  // canonical Albanian spelling, e.g. "Prishtinë"
      "aliases": [string],             // other spellings seen in source tables, e.g. ["Prishtina", "Prishtina Region"]
      "coordinates": { "lat": number, "lon": number },
      "investment_yoy_pct": number,    // latest year-over-year investment growth, %
      "tourism_gap_score": number,     // 0-1, visitor-nights growth minus hotel-capacity growth, normalized across the 7 regions
      "housing_bucket": "prishtina" | "rest"
    }
    // exactly 7 entries, one per region: Prishtinë, Prizren, Pejë, Gjakovë, Gjilan, Ferizaj, Mitrovicë
  ],

  "housing": {
    "prishtina": {
      "index_2018_base": 100,
      "index_latest": number,
      "history": [ { "period": "YYYYQn", "index": number } ]  // quarterly, oldest first
    },
    "rest": {
      "index_2018_base": 100,
      "index_latest": number,
      "history": [ { "period": "YYYYQn", "index": number } ]
    }
  },

  "business_sectors": [
    {
      "code": string,                  // NACE-style section code, e.g. "I"
      "name": string,                  // e.g. "Accommodation and food service"
      "by_municipality": {
        "<municipality name>": { "count_latest": number, "growth_pct": number }
        // one entry per municipality that has data for this sector (up to all 38)
      }
    }
    // must cover at least: I (Accommodation & food service), G (Wholesale/retail), L (Real estate)
  ],

  "insights": {
    "<region name>": string,                 // property-path research brief (filled in by teammate 3; empty string until then)
    "sector:<code>:<municipality>": string   // business-path research brief, key format is literally "sector:<code>:<municipality>"
  }
}
```

## Field notes

- **`regions[].name`** is always the canonical Albanian spelling. Anything
  else seen in a source table (e.g. ASKdata spelling a region "Gjakova"
  instead of "Gjakovë") goes in `aliases`, never replaces `name`.
- **`regions` order is not guaranteed** — always look up by `name`, not index.
- **`tourism_gap_score`** is pre-normalized to 0-1 across the 7 regions by the
  pipeline. Consumers should not renormalize it.
- **`housing_bucket`** is either `"prishtina"` (the Prishtinë region) or
  `"rest"` (every other region) — it's the key used to look up the matching
  entry in `housing`.
- **`housing[bucket].history`** is the quarterly ASKdata series (annual-average
  rows from the source table are dropped, only real "YYYYQn" quarters kept),
  oldest first. `app/forecast.py` fits a linear trend to it to project the
  index 4 quarters ahead and turns that into a plain-language urgency note
  on the property tab. Older data files without this field still work —
  forecasting is simply skipped (`None`) when there isn't enough history.
- **`business_sectors[].by_municipality`** keys are municipality names as
  strings (not a fixed enum here) — the full list of 38 Kosovo municipalities
  is defined by the source data, not by this contract.
- **`insights`** keys are either a region's canonical `name`, or the literal
  string `"sector:<code>:<municipality>"` (e.g. `"sector:I:Prizren"`). Values
  are empty strings (`""`) until teammate 3 fills them in — treat an empty
  string as "no insight yet", not an error.
- All numeric fields are plain JSON numbers (no strings, no units in the
  value — units are documented here, not encoded in the data).

## Files

- `pipeline/sample_data.json` — realistic fake data matching this shape,
  committed early so the app and insights work can start immediately.
- `pipeline/data.json` — real data produced by `pipeline/fetch.py`. Same
  shape as `sample_data.json`, byte-for-byte structure-compatible — swapping
  one for the other requires no code changes elsewhere in the project.
