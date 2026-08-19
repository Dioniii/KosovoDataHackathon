"""
insights.py — research-brief generator (offline, run before the demo).

Fills the "insights" field of the data file with a short, plain-language brief
per region (property path) and per surfaced sector+municipality (business path).

Design decisions (see docs/ANALYSIS_FINDINGS.md and the Prompt 3 spec):
  * Reads pipeline/data.json if it exists, else pipeline/sample_data.json; writes
    back to whichever it read. Never touches the other file.
  * Every brief follows a fixed 3-part shape:
        1. what the numbers show (cites the actual figures),
        2. the one anomaly flag from anomaly.py, if any,
        3. one honest sentence on what the data can't tell you.
  * The LLM is OPTIONAL. With no API key or on any error, a deterministic
    template produces the same 3-part brief straight from the numbers. The
    script ALWAYS produces valid, numbers-grounded text — the LLM only upgrades
    the phrasing, it is never required. This keeps the demo safe.
  * Business path: only the top few municipalities per sector are surfaced, and
    low-confidence (tiny-base) municipalities are skipped so we never write a
    confident brief about a 1->3-unit blip.
  * OFFLINE ONLY — do not call this live inside the Streamlit app.

Usage:
    python pipeline/insights.py                # template briefs (no key needed)
    LLM_API_KEY=sk-... python pipeline/insights.py   # LLM-phrased briefs
    python pipeline/insights.py --force        # regenerate even if already filled

Env vars (all optional):
    LLM_API_KEY       — if unset, template fallback is used for everything.
    LLM_MODEL         — default "gpt-4o-mini".
    LLM_BASE_URL      — OpenAI-compatible base URL, default OpenAI.
"""

from __future__ import annotations

import json
import os
import sys

# import shared logic from ../app
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from scoring import business_score, momentum_by_region  # noqa: E402
from anomaly import region_flags  # noqa: E402

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))

# How many municipalities to surface per sector on the business path.
TOP_N_PER_SECTOR = 3


# --------------------------------------------------------------------------- #
# File I/O — read data.json if present, else sample_data.json; write back same
# --------------------------------------------------------------------------- #
def resolve_data_path() -> str:
    real = os.path.join(PIPELINE_DIR, "data.json")
    return real if os.path.exists(real) else os.path.join(PIPELINE_DIR, "sample_data.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Deterministic template briefs (the always-available fallback)
# --------------------------------------------------------------------------- #
def region_brief_template(region: dict, momentum: float, flag: dict | None) -> str:
    name = region["name"]
    inv = region["investment_yoy_pct"]
    tour = region["tourism_gap_score"]
    part1 = (
        f"{name} scores {momentum:.0f}/100 on momentum this round. "
        f"Construction's share of investment changed by {inv:+.1f} points "
        f"year-on-year, and its tourism-demand score is {tour:.2f} out of 1 "
        f"(visitor-nights growth relative to hotel-capacity growth, ranked "
        f"against the other regions)."
    )
    part2 = f" {flag['message']}" if flag else ""
    part3 = (
        " This is a screening signal, not a valuation: it ranks regions against "
        "each other on a few public indicators and can't tell you actual prices, "
        "yields, or whether a specific property is a good buy."
    )
    return part1 + part2 + part3


def business_brief_template(sector: dict, muni: str, info: dict,
                            tourism_backing: float | None = None) -> str:
    part1 = (
        f"In {muni}, registered {sector['name'].lower()} businesses stand at "
        f"{info['count_latest']} in the latest quarter, a {info['growth_pct']:+.1f}% "
        f"year-on-year change, scoring {info['score']:.0f}/100 for this sector."
    )
    part2 = (
        " Read the growth rate with care — the base here is small, so the "
        "percentage can swing on just a few registrations."
        if info["low_confidence"] else ""
    )
    if sector.get("code") == "I" and tourism_backing is not None:
        if tourism_backing >= 0.5:
            part2 += (
                " Rising hospitality registrations here are backed by relatively "
                "strong visitor demand, which strengthens the signal."
            )
        else:
            part2 += (
                " This score is damped because visitor demand in the region is "
                "on the weaker side, so hospitality growth here is a softer signal."
            )
    part3 = (
        " This is a screening signal from registration counts only — it doesn't "
        "measure revenue, survival, or how crowded the local market already is."
    )
    return part1 + part2 + part3


# --------------------------------------------------------------------------- #
# Optional LLM phrasing (upgrade only; template is the safety net)
# --------------------------------------------------------------------------- #
def llm_rephrase(facts: str) -> str | None:
    """Ask an LLM to phrase `facts` as a clean brief. Returns None on any problem
    so the caller falls back to the template. Never raises."""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    try:
        import urllib.request

        base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        prompt = (
            "Rewrite the following facts as a short, plain-language research "
            "brief (3-5 sentences, no jargon, no bullet points). Do NOT add, "
            "infer, or exaggerate any number or claim beyond what is stated. "
            "Keep every figure exactly as given. Keep the honest limitation "
            "sentence at the end.\n\nFACTS:\n" + facts
        )
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read())
        text = out["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 — never let the LLM break the run
        print(f"  (LLM call failed, using template: {exc})", file=sys.stderr)
        return None


def make_brief(facts_for_llm: str, template_text: str) -> str:
    """LLM phrasing if available and valid, else the deterministic template."""
    return llm_rephrase(facts_for_llm) or template_text


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def generate(data: dict, force: bool = False) -> tuple[int, int]:
    regions = data["regions"]
    insights = data.setdefault("insights", {})
    momentum = momentum_by_region(regions)
    flags = region_flags(regions)

    filled = skipped = 0

    # PROPERTY path — one brief per region
    for region in regions:
        key = region["name"]
        if insights.get(key) and not force:
            skipped += 1
            continue
        template = region_brief_template(region, momentum[key], flags[key])
        insights[key] = make_brief(template, template)
        filled += 1

    # region tourism lookup (name + aliases) for the sector-I demand note
    tourism = {}
    for r in regions:
        tourism[r["name"]] = r["tourism_gap_score"]
        for a in r.get("aliases", []):
            tourism[a] = r["tourism_gap_score"]

    # BUSINESS path — top few qualifying municipalities per sector
    for sector in data["business_sectors"]:
        scored = business_score(sector, regions)
        ranked = sorted(scored.items(), key=lambda kv: -kv[1]["score"])
        surfaced = [(m, info) for m, info in ranked if not info["low_confidence"]]
        # if none qualify, fall back to the top few (still caveated in the text)
        surfaced = (surfaced or ranked)[:TOP_N_PER_SECTOR]
        for muni, info in surfaced:
            key = f"sector:{sector['code']}:{muni}"
            if insights.get(key) and not force:
                skipped += 1
                continue
            backing = tourism.get(muni) if sector.get("code") == "I" else None
            template = business_brief_template(sector, muni, info, backing)
            insights[key] = make_brief(template, template)
            filled += 1

    return filled, skipped


def main() -> None:
    force = "--force" in sys.argv
    path = resolve_data_path()
    data = load(path)
    filled, skipped = generate(data, force=force)
    save(path, data)
    mode = "LLM" if os.getenv("LLM_API_KEY") else "template"
    print(f"insights: filled {filled}, skipped {skipped} "
          f"({mode} mode) -> {os.path.basename(path)}", file=sys.stderr)


if __name__ == "__main__":
    main()
