"""Pure-Python scoring, geometry, and ranking helpers.

No Streamlit imports here on purpose — everything in this module is a plain
function of plain data, so it can be unit tested and reasoned about without
spinning up the app.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0

RAMP_LIGHT = "#86b6ef"
RAMP_DARK = "#0d366b"


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


def rank_business(sector: dict) -> list[dict]:
    """Rank a sector's municipalities by growth_pct for the "invest" tab."""
    rows = [
        {"name": muni, "growth_pct": entry["growth_pct"], "count_latest": entry["count_latest"]}
        for muni, entry in sector["by_municipality"].items()
    ]
    rows.sort(key=lambda r: r["growth_pct"], reverse=True)
    return rows


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
