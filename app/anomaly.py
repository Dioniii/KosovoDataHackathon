"""
anomaly.py — per-region anomaly flags.

Each region gets AT MOST ONE flag: a specific, defensible observation grounded
in that region's own numbers, not a filled-in template. The signal is the gap
between investment momentum and tourism demand, compared on the same normalized
0..100 scale (so "ahead" means ahead relative to the other regions):

    investment clearly ahead of demand  -> "investment_ahead"
    demand clearly ahead of investment  -> "demand_ahead"
    the two roughly in step              -> None  (no flag)

IMPORTANT wording note (docs/ANALYSIS_FINDINGS.md, Issue 2): investment_yoy_pct
is a proxy — the change in construction's SHARE of the investment mix, not
investment growth. Messages say "construction's share of investment" and never
"investment grew/fell X%".
"""

from __future__ import annotations

from typing import Dict, List, Optional

from scoring import normalize

# Distance on the normalized 0..1 scale before a gap counts as real.
GAP_THRESHOLD = 0.25


def region_flags(regions: List[dict]) -> Dict[str, Optional[dict]]:
    """Return {region_name: flag_or_None}. flag = {type, gap, message}."""
    inv = normalize([r["investment_yoy_pct"] for r in regions])
    tour = normalize([r["tourism_gap_score"] for r in regions])

    out: Dict[str, Optional[dict]] = {}
    for i, r in enumerate(regions):
        name = r["name"]
        gap = inv[i] - tour[i]
        inv_share = r["investment_yoy_pct"]
        tour_score = r["tourism_gap_score"]

        if gap >= GAP_THRESHOLD:
            out[name] = {
                "type": "investment_ahead",
                "gap": round(gap, 1),
                "message": (
                    f"In {name} the construction-investment signal sits well "
                    f"above the visitor-demand signal (construction share change "
                    f"{inv_share:+.1f} pts; tourism-demand score {tour_score:.2f}, "
                    f"among the lower ones) — supply-side activity is ahead of "
                    f"measured demand here."
                ),
            }
        elif gap <= -GAP_THRESHOLD:
            out[name] = {
                "type": "demand_ahead",
                "gap": round(gap, 1),
                "message": (
                    f"In {name} the visitor-demand signal sits well above the "
                    f"construction-investment signal (tourism-demand score "
                    f"{tour_score:.2f}; construction share change {inv_share:+.1f} "
                    f"pts) — demand is running ahead of new building, a possible "
                    f"under-served opening."
                ),
            }
        else:
            out[name] = None
    return out


if __name__ == "__main__":
    import json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    pipeline = os.path.join(here, "..", "pipeline")
    path = os.path.join(pipeline, "data.json")
    if not os.path.exists(path):
        path = os.path.join(pipeline, "sample_data.json")
    with open(path, encoding="utf-8") as f:
        regions = json.load(f)["regions"]
    for name, flag in region_flags(regions).items():
        print(f"[{flag['type']:16}] {flag['message']}" if flag
              else f"[{'balanced':16}] {name}: investment and demand roughly in step.")
