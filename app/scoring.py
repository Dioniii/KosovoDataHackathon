"""Pure-Python scoring, geometry, and ranking helpers.

No Streamlit imports here on purpose — everything in this module is a plain
function of plain data, so it can be unit tested and reasoned about without
spinning up the app.

Single source of truth for every formula. Both the Streamlit app (app.py) and
the offline analysis code (pipeline/insights.py, app/anomaly.py) import from
here — nothing re-implements a formula elsewhere.

Two design decisions come from docs/ANALYSIS_FINDINGS.md:
  * Tiny-base floor (Issue 1): municipalities with very few registered
    businesses produce meaningless growth rates (1 -> 3 units reads as +200%).
    Below MIN_COUNT a municipality is marked low_confidence and ranked beneath
    every qualifying one, so a blip can never top a real hub.
  * investment_yoy_pct is a proxy — the YoY change in construction's SHARE of
    the investment mix, not investment growth. Scores only need its relative
    ordering; human-readable text (insights.py) describes it correctly.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0
RAMP_LIGHT = "#86b6ef"
RAMP_DARK = "#0d366b"

# Below this many registered businesses, a municipality's growth_pct is noise.
MIN_COUNT = 15


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. A degenerate (all-equal) input maps to 0.5s."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def proximity_weight(distance_km: float) -> float:
    return 1 / (1 + distance_km / 50)


def momentum_score(
    investment_norm: float, tourism_gap_score: float, w_momentum: float, w_tourism: float
) -> float:
    """Per-region momentum, 0..100, from an already-normalized investment value
    and the (already 0..1) tourism_gap_score. Weights are user-adjustable."""
    total_weight = w_momentum + w_tourism
    if total_weight == 0:
        return 0.0
    return 100 * (w_momentum * investment_norm + w_tourism * tourism_gap_score) / total_weight


def personalized_score(momentum: float, proximity: float) -> float:
    return momentum * proximity


def rank_colors(n: int, light: str = RAMP_LIGHT, dark: str = RAMP_DARK) -> list[str]:
    """n hex colors interpolated from `light` (index 0) to `dark` (index n-1)."""
    if n <= 0:
        return []
    if n == 1:
        return [dark]

    def hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
        return "#" + "".join(f"{int(round(c)):02x}" for c in rgb)

    lo, hi = hex_to_rgb(light), hex_to_rgb(dark)
    colors = []
    for i in range(n):
        t = i / (n - 1)
        rgb = tuple(lo[j] + (hi[j] - lo[j]) * t for j in range(3))
        colors.append(rgb_to_hex(rgb))
    return colors


def compute_property_ranking(
    regions: list[dict],
    anchor_name: str,
    w_momentum: float,
    w_tourism: float,
    exclude_prishtina: bool,
) -> list[dict]:
    """Rank regions by personalizedScore for the "buy property" tab.

    Excludes the Prishtinë (housing_bucket == "prishtina") region entirely
    when `exclude_prishtina` is set, rather than just ranking it lower.
    """
    candidates = [r for r in regions if not (exclude_prishtina and r["housing_bucket"] == "prishtina")]
    if not candidates:
        return []

    anchor = next((r for r in regions if r["name"] == anchor_name), regions[0])
    investment_norm = normalize([r["investment_yoy_pct"] for r in candidates])

    rows = []
    for region, inv_norm in zip(candidates, investment_norm):
        distance_km = haversine_km(
            anchor["coordinates"]["lat"],
            anchor["coordinates"]["lon"],
            region["coordinates"]["lat"],
            region["coordinates"]["lon"],
        )
        proximity = proximity_weight(distance_km)
        momentum = momentum_score(inv_norm, region["tourism_gap_score"], w_momentum, w_tourism)
        rows.append(
            {
                "name": region["name"],
                "investment_yoy_pct": region["investment_yoy_pct"],
                "tourism_gap_score": region["tourism_gap_score"],
                "housing_bucket": region["housing_bucket"],
                "distance_km": distance_km,
                "proximityWeight": proximity,
                "momentumScore": momentum,
                "personalizedScore": personalized_score(momentum, proximity),
            }
        )
    rows.sort(key=lambda r: r["personalizedScore"], reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Business ranking — with the tiny-base floor + sector-I demand adjustment
# --------------------------------------------------------------------------- #
def _region_tourism_lookup(regions: list[dict] | None) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for r in regions or []:
        lookup[r["name"]] = r["tourism_gap_score"]
        for a in r.get("aliases", []):
            lookup[a] = r["tourism_gap_score"]
    return lookup


def score_municipalities(
    sector: dict, regions: list[dict] | None = None, min_count: int = MIN_COUNT
) -> dict[str, dict]:
    """Core sector scorer. Returns
        { municipality: {score 0..100, growth_pct, count_latest, low_confidence} }

    Tiny-base floor: below `min_count` a municipality is low_confidence, is
    normalized separately, and is scaled into 0..49 so it always ranks below any
    qualifying municipality. If nothing qualifies, the whole set is scored and
    all are flagged low_confidence (a caveated ranking beats none).

    Sector "I" (Accommodation & food service) only: growth is damped by the
    parent region's tourism_gap_score before scoring (needs `regions`):
        adjusted = growth_pct * (0.6 + 0.4 * tourism_gap_score)
    so hospitality growth without visitor demand is a weaker signal.
    """
    is_hospitality = sector.get("code") == "I"
    tourism = _region_tourism_lookup(regions) if is_hospitality else {}

    rows = []
    for name, m in sector["by_municipality"].items():
        g = m["growth_pct"]
        if is_hospitality and regions:
            g = g * (0.6 + 0.4 * tourism.get(name, 0.5))  # neutral 0.5 if unmatched
        rows.append(
            {
                "name": name,
                "adj": g,
                "growth_pct": m["growth_pct"],
                "count_latest": m["count_latest"],
                "low_confidence": m["count_latest"] < min_count,
            }
        )

    def info(r: dict, score: float) -> dict:
        return {
            "score": score,
            "growth_pct": r["growth_pct"],
            "count_latest": r["count_latest"],
            "low_confidence": r["low_confidence"],
        }

    qualifying = [r for r in rows if not r["low_confidence"]]
    out: dict[str, dict] = {}
    if qualifying:
        for r, s in zip(qualifying, normalize([r["adj"] for r in qualifying])):
            out[r["name"]] = info(r, round(s * 100, 1))
        low = [r for r in rows if r["low_confidence"]]
        for r, s in zip(low, normalize([r["adj"] for r in low])):
            out[r["name"]] = info(r, round(s * 49, 1))
    else:
        for r, s in zip(rows, normalize([r["adj"] for r in rows])):
            out[r["name"]] = info(r, round(s * 100, 1))
    return out


def business_score(sector: dict, regions: list[dict] | None = None,
                   min_count: int = MIN_COUNT) -> dict[str, dict]:
    """Alias of score_municipalities — the name the analysis code imports."""
    return score_municipalities(sector, regions, min_count)


def rank_business(sector: dict, regions: list[dict] | None = None,
                  min_count: int = MIN_COUNT) -> list[dict]:
    """Rank a sector's municipalities for the "invest" tab.

    Backward-compatible with the frontend's original one-arg call
    `rank_business(sector)`: still returns rows carrying name/growth_pct/
    count_latest (plus score/low_confidence). Now sorted by the floor-aware
    score instead of raw growth_pct, so a 1->3-unit blip no longer ranks first.
    Pass `regions` to also enable the sector-I demand adjustment.
    """
    scored = score_municipalities(sector, regions, min_count)
    rows = [
        {
            "name": name,
            "growth_pct": i["growth_pct"],
            "count_latest": i["count_latest"],
            "score": i["score"],
            "low_confidence": i["low_confidence"],
        }
        for name, i in scored.items()
    ]
    rows.sort(key=lambda r: (r["score"], r["growth_pct"]), reverse=True)
    return rows


def momentum_by_region(regions: list[dict], w_investment: float = 0.5,
                       w_tourism: float = 0.5) -> dict[str, float]:
    """Per-region momentum as {name: 0..100}, built from the same normalize +
    momentum_score primitives the app uses. Used by insights.py and anomaly.py."""
    inv_norm = normalize([r["investment_yoy_pct"] for r in regions])
    return {
        r["name"]: round(momentum_score(inv_norm[i], r["tourism_gap_score"],
                                        w_investment, w_tourism), 1)
        for i, r in enumerate(regions)
    }


def housing_trend_points(housing_bucket: str, housing: dict) -> list[tuple[str, float]]:
    """The only real multi-point history the data has for a region: the 2018
    baseline index and the latest index for its housing bucket."""
    entry = housing.get(housing_bucket, {})
    return [
        ("2018 (base)", entry.get("index_2018_base", 100)),
        ("Latest", entry.get("index_latest")),
    ]


def business_trend_points(entry: dict) -> list[tuple[str, float]]:
    """Two-point enterprise-count trend, backing out the prior period from
    count_latest and growth_pct (there's no separate history in the data)."""
    latest = entry.get("count_latest", 0)
    growth = entry.get("growth_pct", 0.0)
    denom = 1 + growth / 100
    prev = round(latest / denom, 1) if denom > 0 else 0.0
    return [("Previous period", prev), ("Latest", latest)]
