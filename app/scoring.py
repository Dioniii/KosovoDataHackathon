"""scoring.py — shared scoring logic for the Kosovo Property & Investment Screener.

Single source of truth for every formula. Both the Streamlit app (app.py) and
the offline analysis code (pipeline/insights.py, app/anomaly.py) import from
here — nothing re-implements a formula elsewhere.

No Streamlit imports here on purpose — everything in this module is a plain
function of plain data, so it can be unit tested and reasoned about without
spinning up the app.

Two design decisions come from docs/ANALYSIS_FINDINGS.md:
  * Tiny-base floor (Issue 1): municipalities with very few registered
    businesses produce meaningless growth rates (1 -> 3 units reads as +200%).
    Below MIN_COUNT a municipality is marked low_confidence and ranked beneath
    every qualifying one, so a blip can never top a real hub.
  * investment_yoy_pct is a proxy — the YoY change in construction's SHARE of
    the investment mix, not investment growth. Scores only need its relative
    ordering; human-readable text (insights.py) describes it correctly.

Function names are snake_case here, mirroring the frontend's camelCase
equivalents:
    momentum_score   <-> momentumScore
    proximity_weight <-> proximityWeight
    business_score   <-> businessScore

All formulas are documented in docs/DATA_CONTRACT.md. The momentum weights are
USER-ADJUSTABLE inputs (sliders in the app), not fixed constants.

Run directly for a sanity check against the data file:
    python app/scoring.py            # uses pipeline/data.json if present, else sample_data.json
"""

from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional

# ------------------------------------------------------------------ #
# Constants
# ------------------------------------------------------------------ #
EARTH_RADIUS_KM = 6371.0
RAMP_LIGHT = "#86b6ef"
RAMP_DARK = "#0d366b"

# Municipalities with very few registered businesses produce meaningless growth
# rates (1 -> 3 units reads as +200%). Below this count a municipality is scored
# but marked low_confidence and ranked beneath every qualifying municipality.
# See docs/ANALYSIS_FINDINGS.md, Issue 1.
MIN_COUNT = 15


# ------------------------------------------------------------------ #
# Geometry helpers
# ------------------------------------------------------------------ #
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


# ------------------------------------------------------------------ #
# Normalization helpers
# ------------------------------------------------------------------ #
def normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]. A degenerate (all-equal) input maps to 0.5s."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _min_max(values: List[float]) -> List[float]:
    """Min-max normalize to 0..100. Flat series -> all 50 (no false ranking)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [50.0 for _ in values]
    return [(v - lo) / (hi - lo) * 100.0 for v in values]


# ------------------------------------------------------------------ #
# Color ramp
# ------------------------------------------------------------------ #
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


# ------------------------------------------------------------------ #
# Proximity weight  (PROPERTY path — personalization)
# ------------------------------------------------------------------ #
def proximity_weight(distance_km: float) -> float:
    """Weight in (0, 1] that decays with distance from the user's anchor point.

        proximity_weight(0)   = 1.0
        proximity_weight(50)  = 0.5
        proximity_weight(100) ~ 0.33

    The frontend multiplies momentum_score by this to get the personalized
    ranking:  personalized = momentum_score(region) * proximity_weight(dist).
    """
    return 1.0 / (1.0 + distance_km / 50.0)


# ------------------------------------------------------------------ #
# momentum_score  (PROPERTY path — per-region scalar)
# ------------------------------------------------------------------ #
def momentum_score(
    investment_norm: float, tourism_gap_score: float, w_momentum: float, w_tourism: float
) -> float:
    """0..100 blend of investment and tourism signals for a single region.

    NOTE on investment_yoy_pct: per docs/ANALYSIS_FINDINGS.md this field is a
    proxy — the YoY change in construction's SHARE of the investment mix, not
    investment growth. momentum_score only needs its relative ordering across
    regions, which the proxy provides; but any human-readable text must describe
    it correctly (insights.py does this).
    """
    total_weight = w_momentum + w_tourism
    if total_weight == 0:
        return 0.0
    return 100 * (w_momentum * investment_norm + w_tourism * tourism_gap_score) / total_weight


def personalized_score(momentum: float, proximity: float) -> float:
    return momentum * proximity


# ------------------------------------------------------------------ #
# compute_property_ranking  (PROPERTY path — full region table)
# ------------------------------------------------------------------ #
def compute_property_ranking(
    regions: list[dict],
    anchor_name: str,
    w_momentum: float,
    w_tourism: float,
    exclude_prishtina: bool,
) -> list[dict]:
    """Rank regions by personalizedScore for the 'buy property' tab.

    Excludes the Prishtinë (housing_bucket == 'prishtina') region entirely
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
        mom = momentum_score(inv_norm, region["tourism_gap_score"], w_momentum, w_tourism)
        rows.append(
            {
                "name": region["name"],
                "investment_yoy_pct": region["investment_yoy_pct"],
                "tourism_gap_score": region["tourism_gap_score"],
                "housing_bucket": region["housing_bucket"],
                "distance_km": distance_km,
                "proximityWeight": proximity,
                "momentumScore": mom,
                "personalizedScore": personalized_score(mom, proximity),
            }
        )
    rows.sort(key=lambda r: r["personalizedScore"], reverse=True)
    return rows


# ------------------------------------------------------------------ #
# business_score  (BUSINESS path — up to 38 municipalities per sector)
# ------------------------------------------------------------------ #
def _region_tourism_lookup(regions: List[dict]) -> Dict[str, float]:
    """Region name AND every alias -> tourism_gap_score, so a municipality name
    can be matched back to its parent region's tourism signal."""
    lookup: Dict[str, float] = {}
    for r in regions:
        lookup[r["name"]] = r["tourism_gap_score"]
        for a in r.get("aliases", []):
            lookup[a] = r["tourism_gap_score"]
    return lookup


def business_score(sector: dict, regions: List[dict],
                   min_count: int = MIN_COUNT) -> Dict[str, dict]:
    """Score every municipality in one sector. Returns
        { municipality: { "score": 0..100, "growth_pct": float,
                          "count_latest": int, "low_confidence": bool } }

    Two guards, both from docs/ANALYSIS_FINDINGS.md:

    1. Tiny-base floor (Issue 1): municipalities with count_latest < min_count
       are marked low_confidence. Normalization is computed over the QUALIFYING
       municipalities only, and low-confidence ones are scaled into 0..49 so they
       always rank below any qualifying municipality — a 1->3 blip can't top a
       real hub. If nothing qualifies, everything is scored on the full set and
       all are low_confidence (better a caveated ranking than none).

    2. Sector-I demand check: for "Accommodation & food service" only, hospitality
       growth is damped by the parent region's tourism_gap_score before scoring —
       registrations rising without visitor demand is a weaker signal:
           adjusted = growth_pct * (0.6 + 0.4 * tourism_gap_score)
       tourism_gap_score is 0..1, so the multiplier runs 0.6 (no demand backing)
       to 1.0 (full backing). Non-I sectors use raw growth_pct.
    """
    is_hospitality = sector.get("code") == "I"
    tourism = _region_tourism_lookup(regions) if is_hospitality else {}

    rows = []
    for name, m in sector["by_municipality"].items():
        g = m["growth_pct"]
        if is_hospitality:
            g = g * (0.6 + 0.4 * tourism.get(name, 0.5))  # neutral 0.5 if unmatched
        rows.append({
            "name": name,
            "adj_growth": g,
            "growth_pct": m["growth_pct"],
            "count_latest": m["count_latest"],
            "low_confidence": m["count_latest"] < min_count,
        })

    qualifying = [r for r in rows if not r["low_confidence"]]
    result: Dict[str, dict] = {}

    if qualifying:
        norm = _min_max([r["adj_growth"] for r in qualifying])
        for r, s in zip(qualifying, norm):
            result[r["name"]] = _row(r, round(s, 1))
        low = [r for r in rows if r["low_confidence"]]
        if low:
            lnorm = _min_max([r["adj_growth"] for r in low])
            for r, s in zip(low, lnorm):
                result[r["name"]] = _row(r, round(s * 0.49, 1))
    else:
        norm = _min_max([r["adj_growth"] for r in rows])
        for r, s in zip(rows, norm):
            result[r["name"]] = _row(r, round(s, 1))
    return result


def _row(r: dict, score: float) -> dict:
    return {
        "score": score,
        "growth_pct": r["growth_pct"],
        "count_latest": r["count_latest"],
        "low_confidence": r["low_confidence"],
    }


def ranked_business(sector: dict, regions: List[dict],
                    min_count: int = MIN_COUNT) -> List[tuple]:
    """Convenience: business_score sorted best-first as [(municipality, info), ...]."""
    scored = business_score(sector, regions, min_count)
    return sorted(scored.items(), key=lambda kv: -kv[1]["score"])


def rank_business(sector: dict) -> list[dict]:
    """Rank a sector's municipalities by growth_pct for the 'invest' tab."""
    rows = [
        {"name": muni, "growth_pct": entry["growth_pct"], "count_latest": entry["count_latest"]}
        for muni, entry in sector["by_municipality"].items()
    ]
    rows.sort(key=lambda r: r["growth_pct"], reverse=True)
    return rows


# ------------------------------------------------------------------ #
# Housing / business trend helpers
# ------------------------------------------------------------------ #
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


# ------------------------------------------------------------------ #
# Self-test
# ------------------------------------------------------------------ #
def load_data(path: Optional[str] = None) -> dict:
    """Load pipeline/data.json if present, else pipeline/sample_data.json."""
    here = os.path.dirname(os.path.abspath(__file__))
    pipeline = os.path.join(here, "..", "pipeline")
    if path is None:
        real = os.path.join(pipeline, "data.json")
        path = real if os.path.exists(real) else os.path.join(pipeline, "sample_data.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    data = load_data()
    regions = data["regions"]

    print("=== momentum_score (50/50) ===")
    inv_norms = normalize([r["investment_yoy_pct"] for r in regions])
    for region, inv_norm in sorted(
        zip(regions, inv_norms), key=lambda x: -momentum_score(x[1], x[0]["tourism_gap_score"], 0.5, 0.5)
    ):
        s = momentum_score(inv_norm, region["tourism_gap_score"], 0.5, 0.5)
        print(f"  {s:5.1f}  {region['name']}")

    print("\n=== business ranking (with tiny-base floor) ===")
    for sector in data["business_sectors"]:
        print(f"\n  [{sector['code']}] {sector['name']}:")
        for name, info in ranked_business(sector, regions)[:5]:
            tag = "  (!low-confidence)" if info["low_confidence"] else ""
            print(f"    {info['score']:5.1f}  {name:<14} "
                  f"{info['count_latest']:>4}u {info['growth_pct']:+.1f}%{tag}")
