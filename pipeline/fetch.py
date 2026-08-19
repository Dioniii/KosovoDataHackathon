"""Pipeline that fetches Kosovo regional/business data and writes pipeline/data.json.

Sources:
  - ASKdata (Kosovo Agency of Statistics) PXWeb API for regional investment,
    tourism, housing-price and business-registration tables.
  - World Bank API for national GDP growth and FDI inflows.

Output shape matches docs/DATA_CONTRACT.md exactly, so pipeline/data.json can
swap in for pipeline/sample_data.json with zero changes elsewhere in the
project.

Every successful HTTP response is cached to disk under pipeline/.cache/, and
a live fetch that fails after retries falls back to the last cached response
for that exact request. That means a flaky connection degrades the run
instead of losing data, and the script is safe to re-run: it always rebuilds
data.json from scratch from (fresh-or-cached) source data and writes it
atomically, so re-running never duplicates or corrupts output.

Usage: python pipeline/fetch.py   (from anywhere; requires `requests`)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import requests

ASKDATA_BASE = "https://askdata.rks-gov.net/api/v1/en/ASKdata"
WORLDBANK_BASE = "https://api.worldbank.org/v2/country/XKX/indicator"

PIPELINE_DIR = Path(__file__).parent
CACHE_DIR = PIPELINE_DIR / ".cache"
OUTPUT_PATH = PIPELINE_DIR / "data.json"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 2.0

# ASKdata tables spell regions differently from one another (e.g. ht02.px
# uses "Peja" while ht03.px and inv04.px use "Pejë"). Every spelling we've
# seen in a source table is listed here, mapped to the canonical Albanian
# name used throughout this project.
REGION_ALIASES: dict[str, list[str]] = {
    "Prishtinë": ["Prishtinë", "Prishtina", "Prishtina Region"],
    "Prizren": ["Prizren", "Prizreni", "Prizren Region"],
    "Pejë": ["Pejë", "Peja", "Peja Region"],
    "Gjakovë": ["Gjakovë", "Gjakova", "Gjakova Region"],
    "Gjilan": ["Gjilan", "Gjilani", "Gnjilane", "Gjilan Region"],
    "Ferizaj": ["Ferizaj", "Ferizaji", "Ferizaj Region", "Uroševac"],
    "Mitrovicë": ["Mitrovicë", "Mitrovica", "Mitrovica Region"],
}

REGION_COORDINATES: dict[str, dict[str, float]] = {
    "Prishtinë": {"lat": 42.6629, "lon": 21.1655},
    "Prizren": {"lat": 42.2139, "lon": 20.7397},
    "Pejë": {"lat": 42.6591, "lon": 20.2883},
    "Gjakovë": {"lat": 42.3803, "lon": 20.4308},
    "Gjilan": {"lat": 42.4636, "lon": 21.4694},
    "Ferizaj": {"lat": 42.3706, "lon": 21.1553},
    "Mitrovicë": {"lat": 42.8914, "lon": 20.8660},
}

# code -> (display name, predicate matching the ASKdata sector valueText)
SECTOR_DEFS: list[tuple[str, str, Callable[[str], bool]]] = [
    ("I", "Accommodation and food service", lambda t: t.startswith("I ")),
    ("G", "Wholesale and retail trade", lambda t: t.startswith("G ")),
    ("L", "Real estate activities", lambda t: t.startswith("L ")),
]


# --------------------------------------------------------------------------
# HTTP + disk cache
# --------------------------------------------------------------------------


def _cache_path(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    basename = key.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", basename)[:48]
    return CACHE_DIR / f"{safe}_{digest}.json"


def fetch_json(url: str, *, body: Optional[dict] = None) -> dict:
    """GET or POST (if body given) a JSON endpoint, with retries + disk cache.

    On success, caches the response. On total failure after retries, falls
    back to the last cached response for this exact request if one exists.
    """
    cache_key = url if body is None else f"{url}|{json.dumps(body, sort_keys=True)}"
    cache_file = _cache_path(cache_key)

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if body is None:
                response = requests.get(url, timeout=REQUEST_TIMEOUT)
            else:
                response = requests.post(url, json=body, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            return data
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    if cache_file.exists():
        print(
            f"warning: live fetch failed for {url} ({last_error}); using cached response",
            file=sys.stderr,
        )
        return json.loads(cache_file.read_text(encoding="utf-8"))

    raise RuntimeError(f"failed to fetch {url} and no cached response is available: {last_error}")


# --------------------------------------------------------------------------
# PXWeb helpers
# --------------------------------------------------------------------------


def px_table_url(*path_parts: str) -> str:
    return "/".join([ASKDATA_BASE, *(requests.utils.quote(p, safe="") for p in path_parts)])


def px_variable(metadata: dict, code: str) -> dict:
    for var in metadata["variables"]:
        if var["code"] == code:
            return var
    raise KeyError(f"variable {code!r} not found in table metadata")


def px_resolve_code(metadata: dict, var_code: str, predicate: Callable[[str], bool]) -> str:
    var = px_variable(metadata, var_code)
    for code, text in zip(var["values"], var["valueTexts"]):
        if predicate(text):
            return code
    raise KeyError(f"no value of {var_code!r} matches predicate")


def px_latest_two_time_codes(metadata: dict, var_code: str) -> tuple[str, str]:
    """Return (latest_code, previous_code) for a time variable, newest first."""
    var = px_variable(metadata, var_code)
    pairs = sorted(zip(var["values"], var["valueTexts"]), key=lambda p: -int(p[1]))
    return pairs[0][0], pairs[1][0]


def px_region_code_map(metadata: dict, var_code: str) -> dict[str, str]:
    """Map canonical region name -> this table's source code for that region."""
    variant_to_canonical = {
        variant.lower(): canonical
        for canonical, variants in REGION_ALIASES.items()
        for variant in variants
    }
    var = px_variable(metadata, var_code)
    result: dict[str, str] = {}
    for code, text in zip(var["values"], var["valueTexts"]):
        canonical = variant_to_canonical.get(text.strip().lower())
        if canonical:
            result[canonical] = code
    return result


def px_query(table_path: str, query: list[dict]) -> dict:
    url = px_table_url(*table_path.split("/"))
    return fetch_json(url, body={"query": query, "response": {"format": "json"}})


def px_metadata(table_path: str) -> dict:
    url = px_table_url(*table_path.split("/"))
    return fetch_json(url)


def px_value_at(data: dict, key: list[str]) -> Optional[float]:
    for row in data["data"]:
        if row["key"] == key:
            raw = row["values"][0]
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


def pct_change(old: Optional[float], new: Optional[float]) -> float:
    if old is None or new is None:
        return 0.0
    if old == 0:
        return 0.0
    return round((new - old) / old * 100, 2)


# --------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------


def build_national() -> dict:
    def latest_value(indicator: str) -> float:
        _, records = fetch_json(f"{WORLDBANK_BASE}/{indicator}?format=json&per_page=20")
        for record in records:
            if record.get("value") is not None:
                return round(float(record["value"]), 2)
        raise RuntimeError(f"no non-null World Bank observation found for {indicator}")

    return {
        "gdp_growth_pct": latest_value("NY.GDP.MKTP.KD.ZG"),
        "fdi_pct_gdp": latest_value("BX.KLT.DINV.WD.GD.ZS"),
        "last_updated": date.today().isoformat(),
    }


def build_investment_yoy() -> dict[str, float]:
    """Year-over-year investment_yoy_pct per region from ASKdata inv04.px.

    inv04.px reports each region's investment *composition* (category shares
    that sum to 100%), not an absolute investment level, so there is no raw
    total to take a YoY growth rate of. As a directional proxy we use the
    year-over-year percentage-point change in the "Investment in
    Construction" share, the largest and most stable category and the one
    most relevant to a property-investment read of a region.
    """
    table = "Investimet në Ndërrmarrje/inv04.px"
    metadata = px_metadata(table)
    region_codes = px_region_code_map(metadata, "Regjionet")
    construction_code = px_resolve_code(
        metadata, "Variabla", lambda t: t.strip().lower() == "investment in construction"
    )
    latest_year, prev_year = px_latest_two_time_codes(metadata, "Viti")

    data = px_query(
        table,
        [
            {"code": "Viti", "selection": {"filter": "item", "values": [latest_year, prev_year]}},
            {
                "code": "Regjionet",
                "selection": {"filter": "item", "values": list(region_codes.values())},
            },
            {"code": "Variabla", "selection": {"filter": "item", "values": [construction_code]}},
        ],
    )

    result = {}
    for region, code in region_codes.items():
        latest = px_value_at(data, [latest_year, code, construction_code])
        prev = px_value_at(data, [prev_year, code, construction_code])
        result[region] = round((latest or 0.0) - (prev or 0.0), 2)
    return result


def build_tourism_gap() -> dict[str, float]:
    """0-1 tourism_gap_score per region: visitor-nights growth minus hotel-
    capacity (bed count) growth, min-max normalized across the 7 regions."""
    nights_table = "Tourism and hotels/Treguesit vjetor/ht03.px"
    beds_table = "Tourism and hotels/Treguesit vjetor/ht02.px"

    nights_meta = px_metadata(nights_table)
    nights_regions = px_region_code_map(nights_meta, "Regjionet")
    # ASKdata's own valueText for this option is misspelled ("Nihgts"), so
    # match by elimination against the sibling "Visitors" option instead.
    nights_var = px_resolve_code(
        nights_meta, "Vizitor/nete", lambda t: not t.strip().lower().startswith("visitor")
    )
    nights_latest_yr, nights_prev_yr = px_latest_two_time_codes(nights_meta, "Viti")
    nights_data = px_query(
        nights_table,
        [
            {
                "code": "Regjionet",
                "selection": {"filter": "item", "values": list(nights_regions.values())},
            },
            {
                "code": "Viti",
                "selection": {"filter": "item", "values": [nights_latest_yr, nights_prev_yr]},
            },
            {"code": "Vizitor/nete", "selection": {"filter": "item", "values": [nights_var]}},
        ],
    )

    beds_meta = px_metadata(beds_table)
    beds_regions = px_region_code_map(beds_meta, "Regjioni")
    beds_var = px_resolve_code(beds_meta, "Variabla", lambda t: t.strip().lower() == "beds")
    beds_latest_yr, beds_prev_yr = px_latest_two_time_codes(beds_meta, "Viti")
    beds_data = px_query(
        beds_table,
        [
            {
                "code": "Regjioni",
                "selection": {"filter": "item", "values": list(beds_regions.values())},
            },
            {
                "code": "Viti",
                "selection": {"filter": "item", "values": [beds_latest_yr, beds_prev_yr]},
            },
            {"code": "Variabla", "selection": {"filter": "item", "values": [beds_var]}},
        ],
    )

    gaps: dict[str, float] = {}
    for region in REGION_COORDINATES:
        n_code = nights_regions[region]
        nights_latest = px_value_at(nights_data, [n_code, nights_latest_yr, nights_var])
        nights_prev = px_value_at(nights_data, [n_code, nights_prev_yr, nights_var])
        nights_growth = pct_change(nights_prev, nights_latest)

        b_code = beds_regions[region]
        beds_latest = px_value_at(beds_data, [b_code, beds_latest_yr, beds_var])
        beds_prev = px_value_at(beds_data, [b_code, beds_prev_yr, beds_var])
        beds_growth = pct_change(beds_prev, beds_latest)

        gaps[region] = nights_growth - beds_growth

    lo, hi = min(gaps.values()), max(gaps.values())
    if hi == lo:
        return {region: 0.5 for region in gaps}
    return {region: round((gap - lo) / (hi - lo), 3) for region, gap in gaps.items()}


def build_regions() -> list[dict]:
    investment_yoy = build_investment_yoy()
    tourism_gap = build_tourism_gap()

    regions = []
    for name, coords in REGION_COORDINATES.items():
        aliases = [a for a in REGION_ALIASES[name] if a != name]
        regions.append(
            {
                "name": name,
                "aliases": aliases,
                "coordinates": coords,
                "investment_yoy_pct": investment_yoy.get(name, 0.0),
                "tourism_gap_score": tourism_gap.get(name, 0.5),
                "housing_bucket": "prishtina" if name == "Prishtinë" else "rest",
            }
        )
    return regions


def _quarterly_periods(metadata: dict, var_code: str) -> list[tuple[str, str]]:
    """(code, label) for this variable's actual "YYYYQn" entries, oldest first.

    The source table mixes quarterly rows ("2019Q3") with annual-average rows
    ("Annual average 2019") in the same variable — only the former form a
    regular time series a trend can be fit to, so the latter are dropped here.
    """
    var = px_variable(metadata, var_code)
    parsed = []
    for code, text in zip(var["values"], var["valueTexts"]):
        m = re.match(r"^(\d{4})Q([1-4])$", text.strip())
        if m:
            year, quarter = int(m.group(1)), int(m.group(2))
            parsed.append((code, text.strip(), year * 4 + quarter))
    parsed.sort(key=lambda p: p[2])
    return [(code, label) for code, label, _ in parsed]


def build_housing() -> dict:
    table = "Prices/Indeksi i Çmimeve të Pronës Banesore/IPBN02.px"
    metadata = px_metadata(table)
    periods = _quarterly_periods(metadata, "Year/quarter")
    period_codes = [code for code, _ in periods]

    pristina_var = px_resolve_code(
        metadata, "Variables", lambda t: "pristina" in t.lower() and t.lower().startswith("index")
    )
    other_var = px_resolve_code(
        metadata,
        "Variables",
        lambda t: "other regions" in t.lower() and t.lower().startswith("index"),
    )

    data = px_query(
        table,
        [
            {"code": "Year/quarter", "selection": {"filter": "item", "values": period_codes}},
            {
                "code": "Variables",
                "selection": {"filter": "item", "values": [pristina_var, other_var]},
            },
        ],
    )

    def series(var_code: str) -> list[dict]:
        points = []
        for code, label in periods:
            value = px_value_at(data, [code, var_code])
            if value is not None:
                points.append({"period": label, "index": value})
        return points

    def bucket(var_code: str) -> dict:
        points = series(var_code)
        if not points:
            raise RuntimeError(f"no housing index history found for variable {var_code!r}")
        return {
            "index_2018_base": 100,
            "index_latest": points[-1]["index"],
            "history": points,
        }

    return {"prishtina": bucket(pristina_var), "rest": bucket(other_var)}


def build_business_sectors() -> list[dict]:
    table = "Statistical business register/Quarterly indicators/enterprises03.px"
    metadata = px_metadata(table)

    municipality_var = px_variable(metadata, "municipality")
    municipalities = dict(zip(municipality_var["values"], municipality_var["valueTexts"]))

    latest_year, prev_year = px_latest_two_time_codes(metadata, "year")
    q4_code = px_resolve_code(metadata, "period", lambda t: t.strip().upper() == "Q4")

    sector_codes = {
        code: px_resolve_code(metadata, "Code/Sector of economic activity", predicate)
        for code, _, predicate in SECTOR_DEFS
    }

    data = px_query(
        table,
        [
            {
                "code": "municipality",
                "selection": {"filter": "item", "values": list(municipalities.keys())},
            },
            {"code": "year", "selection": {"filter": "item", "values": [latest_year, prev_year]}},
            {"code": "period", "selection": {"filter": "item", "values": [q4_code]}},
            {
                "code": "Code/Sector of economic activity",
                "selection": {"filter": "item", "values": list(sector_codes.values())},
            },
        ],
    )

    sectors = []
    for code, name, _ in SECTOR_DEFS:
        sector_code = sector_codes[code]
        by_municipality = {}
        for muni_code, muni_name in municipalities.items():
            latest = px_value_at(data, [muni_code, latest_year, q4_code, sector_code])
            prev = px_value_at(data, [muni_code, prev_year, q4_code, sector_code])
            if latest is None:
                continue
            by_municipality[muni_name] = {
                "count_latest": int(latest),
                "growth_pct": pct_change(prev, latest),
            }
        sectors.append({"code": code, "name": name, "by_municipality": by_municipality})
    return sectors


def build_insights(regions: list[dict], sectors: list[dict]) -> dict:
    insights: dict[str, str] = {region["name"]: "" for region in regions}
    for sector in sectors:
        for municipality in sector["by_municipality"]:
            insights[f"sector:{sector['code']}:{municipality}"] = ""
    return insights


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> None:
    print("fetching national indicators (World Bank)...", file=sys.stderr)
    national = build_national()

    print("fetching regional investment/tourism data (ASKdata)...", file=sys.stderr)
    regions = build_regions()

    print("fetching housing price index (ASKdata)...", file=sys.stderr)
    housing = build_housing()

    print("fetching business sector registrations (ASKdata)...", file=sys.stderr)
    business_sectors = build_business_sectors()

    insights = build_insights(regions, business_sectors)

    output = {
        "national": national,
        "regions": regions,
        "housing": housing,
        "business_sectors": business_sectors,
        "insights": insights,
    }

    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(OUTPUT_PATH)
    print(f"wrote {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
