"""forecast.py — next-year housing-price projection and investment urgency.

Fits a simple linear trend (ordinary least squares) to the quarterly housing
price-index history the pipeline now keeps (see pipeline/fetch.py
build_housing()) and extrapolates 4 quarters ahead to get a predicted index
one year from the latest known quarter. "Urgency" is just that predicted
year-over-year change bucketed into plain-language tiers, downgraded to
"watch" whenever the trend fit is too weak to trust — nothing fancier, so
it's easy to explain to a non-technical user and to defend in a demo.

No Streamlit/pandas here on purpose, same as scoring.py: a plain function of
plain data, unit-testable on its own.

Run directly for a sanity check against the data file:
    python app/forecast.py        # uses pipeline/data.json if present, else sample_data.json
"""

from __future__ import annotations

from typing import Optional, TypedDict

QUARTERS_PER_YEAR = 4
# Need at least a year of quarters before a trend line means anything.
MIN_POINTS_FOR_TREND = 4

# Thresholds on predicted YoY %% change. Tuned to be readable, not calibrated
# against any external benchmark — this is a screening signal, not a model
# with a backtested error bound.
HIGH_URGENCY_YOY_PCT = 8.0
MEDIUM_URGENCY_YOY_PCT = 3.0
FALLING_YOY_PCT = -3.0

# Below this R^2 the trend line barely explains the history, so a forecast
# built on it shouldn't tell anyone to act fast — downgrade to "watch".
MIN_TRUSTED_R2 = 0.3

URGENCY_LABELS = {
    "high": "High urgency",
    "medium": "Rising",
    "low": "Steady",
    "watch": "Watch",
}


class Forecast(TypedDict):
    predicted_index: float
    predicted_yoy_pct: float
    urgency: str  # "high" | "medium" | "low" | "watch"
    r_squared: float


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Ordinary least squares slope/intercept for y = slope*x + intercept."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return 0.0, mean_y
    slope = covariance / variance
    intercept = mean_y - slope * mean_x
    return slope, intercept


def _r_squared(xs: list[float], ys: list[float], slope: float, intercept: float) -> float:
    mean_y = sum(ys) / len(ys)
    ss_total = sum((y - mean_y) ** 2 for y in ys)
    if ss_total == 0:
        return 1.0
    ss_residual = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    return max(0.0, 1 - ss_residual / ss_total)


def urgency_tier(predicted_yoy_pct: float, r_squared: float) -> str:
    """Plain-language urgency label from predicted YoY %% change.

    A low-confidence fit (r_squared < MIN_TRUSTED_R2) is always "watch"
    regardless of the predicted number — a shaky trend shouldn't tell anyone
    to act fast, and a clearly falling trend is also "watch" (worth
    monitoring, not a reason to rush in).
    """
    if r_squared < MIN_TRUSTED_R2 or predicted_yoy_pct <= FALLING_YOY_PCT:
        return "watch"
    if predicted_yoy_pct >= HIGH_URGENCY_YOY_PCT:
        return "high"
    if predicted_yoy_pct >= MEDIUM_URGENCY_YOY_PCT:
        return "medium"
    return "low"


def forecast_next_year(
    history: list[dict], horizon_quarters: int = QUARTERS_PER_YEAR
) -> Optional[Forecast]:
    """Fit a linear trend to `history` ([{"period", "index"}, oldest first])
    and project `horizon_quarters` ahead of the latest point.

    Returns None if there isn't enough history to fit a trend on
    (fewer than MIN_POINTS_FOR_TREND quarters).
    """
    points = [h for h in history if h.get("index") is not None]
    if len(points) < MIN_POINTS_FOR_TREND:
        return None

    xs = list(range(len(points)))
    ys = [p["index"] for p in points]
    slope, intercept = _linear_fit(xs, ys)
    r2 = _r_squared(xs, ys, slope, intercept)

    current = ys[-1]
    future_x = xs[-1] + horizon_quarters
    predicted_index = slope * future_x + intercept
    predicted_yoy_pct = ((predicted_index - current) / current * 100) if current else 0.0

    return {
        "predicted_index": round(predicted_index, 1),
        "predicted_yoy_pct": round(predicted_yoy_pct, 1),
        "urgency": urgency_tier(predicted_yoy_pct, r2),
        "r_squared": round(r2, 2),
    }


def housing_bucket_forecast(housing: dict, housing_bucket: str) -> Optional[Forecast]:
    """Convenience: forecast for one housing bucket ("prishtina" or "rest"),
    falling back to None if that bucket has no quarterly history (e.g. the
    2-point sample data before a real pipeline run)."""
    entry = housing.get(housing_bucket, {})
    return forecast_next_year(entry.get("history", []))


def urgency_note(forecast: Optional[Forecast], region_name: str) -> tuple[str, str]:
    """(alert_kind, message): one plain-English sentence a non-technical reader
    can understand at a glance, plus which Streamlit alert style to show it in
    (alert_kind is "error" | "warning" | "success" | "info" — pass straight to
    the matching st.<alert_kind>() call). No numbers jargon (no "R²", no
    "index", no "segment") — just what it means for someone deciding whether
    to act now or wait.
    """
    if forecast is None:
        return "info", f"Not enough price history yet to predict {region_name}'s market."

    pct = forecast["predicted_yoy_pct"]
    tier = forecast["urgency"]

    if tier == "high":
        return "error", (
            f"🔥 If you wait a year, prices in {region_name} could be about "
            f"**{pct:.0f}% higher** — this looks like a good time to act."
        )
    if tier == "medium":
        return "warning", (
            f"📈 Prices in {region_name} are trending up — expect roughly "
            f"**{pct:.0f}% higher** a year from now if that continues."
        )
    if tier == "low":
        return "success", (
            f"🟢 Prices in {region_name} have been steady — no big change expected "
            "over the next year, so there's no rush."
        )
    if forecast["r_squared"] < MIN_TRUSTED_R2:
        return "info", (
            f"👀 Recent prices in {region_name} have been bouncing around too much "
            "to predict clearly — worth keeping an eye on."
        )
    return "info", f"👀 Prices in {region_name} have recently cooled off — no rush to buy right now."


def attach_urgency(rows: list[dict], housing: dict) -> list[dict]:
    """Return `rows` (each needs a "housing_bucket" key, as compute_property_
    ranking's output does) with a "forecast" key merged in — None where there
    isn't enough history to project."""
    cache: dict[str, Optional[Forecast]] = {}
    out = []
    for row in rows:
        bucket = row["housing_bucket"]
        if bucket not in cache:
            cache[bucket] = housing_bucket_forecast(housing, bucket)
        out.append({**row, "forecast": cache[bucket]})
    return out


# ------------------------------------------------------------------ #
# Self-test
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    from scoring import load_data

    data = load_data()
    for bucket in ("prishtina", "rest"):
        fc = housing_bucket_forecast(data["housing"], bucket)
        if fc is None:
            print(f"{bucket:10} not enough quarterly history to forecast")
        else:
            print(
                f"{bucket:10} predicted index in 1yr: {fc['predicted_index']:6.1f}  "
                f"YoY: {fc['predicted_yoy_pct']:+5.1f}%  "
                f"urgency: {fc['urgency']:6}  (fit R^2={fc['r_squared']})"
            )
