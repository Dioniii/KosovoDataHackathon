"""
scoring.py — shared scoring logic for the Kosovo Property & Investment Screener.

Single source of truth for the formulas. The Streamlit app imports these
directly; the insight generator (pipeline/insights.py) imports them too. Do not
re-implement any of these anywhere else.

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

# Municipalities with very few registered businesses produce meaningless growth
# rates (1 -> 3 units reads as +200%). Below this count a municipality is scored
# but marked low_confidence and ranked beneath every qualifying municipality.
# See docs/ANALYSIS_FINDINGS.md, Issue 1.
MIN_COUNT = 15


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _min_max(values: List[float]) -> List[float]:
    """Min-max normalize to 0..100. Flat series -> all 50 (no false ranking)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi == lo:
        return [50.0 for _ in values]
    return [(v - lo) / (hi - lo) * 100.0 for v in values]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------- #
# proximity_weight  (PROPERTY path — personalization)
# --------------------------------------------------------------------------- #
def proximity_weight(distance_km: float) -> float:
    """Weight in (0, 1] that decays with distance from the user's anchor point.

        proximity_weight(0)   = 1.0
        proximity_weight(50)  = 0.5
        proximity_weight(100) ~ 0.33

    The frontend multiplies momentum_score by this to get the personalized
    ranking:  personalized = momentum_score(region) * proximity_weight(dist).
    """
    return 1.0 / (1.0 + distance_km / 50.0)


# --------------------------------------------------------------------------- #
# momentum_score  (PROPERTY path — 7 regions)
# --------------------------------------------------------------------------- #
def momentum_score(regions: List[dict], w_investment: float = 0.5,
                   w_tourism: float = 0.5) -> Dict[str, float]:
    """0..100 blend of investment and tourism signals across the regions.

    Both inputs are min-max normalized across the regions first (they are on
    different scales — a %-point change vs. a 0..1 score), then blended with the
    given weights. Weights are renormalized to sum to 1, so passing (1, 0) gives
    a pure investment ranking and (0, 1) a pure tourism ranking.

    NOTE on investment_yoy_pct: per docs/ANALYSIS_FINDINGS.md this field is a
    proxy — the YoY change in construction's SHARE of the investment mix, not
    investment growth. momentum_score only needs its relative ordering across
    regions, which the proxy provides; but any human-readable text must describe
    it correctly (insights.py does this).
    """
    total = w_investment + w_tourism
    if total <= 0:
        w_investment = w_tourism = 0.5
        total = 1.0
    w_investment, w_tourism = w_investment / total, w_tourism / total

    inv = _min_max([r["investment_yoy_pct"] for r in regions])
    tour = _min_max([r["tourism_gap_score"] for r in regions])
    return {
        regions[i]["name"]: round(w_investment * inv[i] + w_tourism * tour[i], 1)
        for i in range(len(regions))
    }


# --------------------------------------------------------------------------- #
# business_score  (BUSINESS path — up to 38 municipalities per sector)
# --------------------------------------------------------------------------- #
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
        # low-confidence rows: scaled into 0..49, always below qualifying ones
        low = [r for r in rows if r["low_confidence"]]
        if low:
            lnorm = _min_max([r["adj_growth"] for r in low])
            for r, s in zip(low, lnorm):
                result[r["name"]] = _row(r, round(s * 0.49, 1))
    else:
        # nothing clears the floor — score the whole set, all caveated
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


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
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
    for name, s in sorted(momentum_score(regions).items(), key=lambda kv: -kv[1]):
        print(f"  {s:5.1f}  {name}")

    print("\n=== business ranking (with tiny-base floor) ===")
    for sector in data["business_sectors"]:
        print(f"\n  [{sector['code']}] {sector['name']}:")
        for name, info in ranked_business(sector, regions)[:5]:
            tag = "  (!low-confidence)" if info["low_confidence"] else ""
            print(f"    {info['score']:5.1f}  {name:<14} "
                  f"{info['count_latest']:>4}u {info['growth_pct']:+.1f}%{tag}")
