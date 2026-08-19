"""ai_advisor.py — the "AI Summary" chat advisor.

A short, fixed intake (property vs. business, then a couple of grounding
questions) followed by ONE Ollama Cloud call that synthesizes a personalized
recommendation from the user's answers plus this app's own already-computed
rankings (scoring.py) — the LLM only phrases and personalizes, it never
invents numbers. If the live call fails for any reason (bad/missing key,
network issue), a deterministic template built from the same facts is shown
instead, so the chat never just breaks mid-demo.

Ollama Cloud: POST https://ollama.com/api/chat, Authorization: Bearer <key>.
The key is read from st.secrets["ollama"]["api_key"] (see
.streamlit/secrets.toml.example), or the OLLAMA_API_KEY env var as a
fallback — never hardcoded here.
"""

from __future__ import annotations

import json
import os
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import streamlit as st

from scoring import compute_property_ranking, ranked_business

OLLAMA_URL = "https://ollama.com/api/chat"
DEFAULT_MODEL = "gpt-oss:120b-cloud"

# st.secrets only looks relative to Streamlit's launch cwd (or ~/.streamlit),
# but app.py is documented to run from inside app/ while secrets.toml lives
# at the repo root — so st.secrets alone would silently miss it depending on
# where `streamlit run` was launched from. Resolve the same way data_loader.py
# resolves pipeline/, via Path(__file__), so this works regardless of cwd.
_SECRETS_FILE = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"

SYSTEM_PROMPT = (
    "You are the research-brief assistant inside a Kosovo property/investment "
    "screener for the diaspora. You are given (a) numbers the app already "
    "computed and (b) what the user told you about their goals. Write a short "
    "(4-7 sentence), plain-language, personalized recommendation. Rules: never "
    "invent, adjust, or exaggerate any number — use only the figures given, "
    "verbatim; reference the user's own stated preference so it reads as "
    "personalized, not generic; you may recommend more than one of the given "
    "top options; end with one honest sentence noting this is a screening "
    "signal from public statistics, not financial advice, and doesn't replace "
    "real due diligence."
)

BUDGET_TIERS = ["Under a threshold", "Around it", "Above it"]
PROPERTY_PRIORITIES = {
    "Investment momentum": (1.0, 0.2),
    "Tourism demand": (0.2, 1.0),
    "Balance both": (0.5, 0.5),
}
RISK_PREFERENCES = ["Fast-growing, higher risk", "Stable, lower risk"]

STATE_PREFIX = "adv_"


# --------------------------------------------------------------------------- #
# Ollama Cloud client
# --------------------------------------------------------------------------- #
def _file_secret(name: str) -> str:
    try:
        with _SECRETS_FILE.open("rb") as f:
            return tomllib.load(f).get("ollama", {}).get(name, "")
    except Exception:
        return ""


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets["ollama"].get(name)
        if value:
            return value
    except Exception:
        pass
    return _file_secret(name) or os.environ.get(f"OLLAMA_{name.upper()}", default)


def call_ollama(messages: list[dict], *, timeout: int = 45) -> Optional[str]:
    """One-shot Ollama Cloud chat call. Returns the assistant's text, or None
    on any failure — caller falls back to a template, this never raises."""
    api_key = _secret("api_key")
    if not api_key:
        return None
    model = _secret("model", DEFAULT_MODEL)
    body = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
        return (out.get("message", {}).get("content") or "").strip() or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


# --------------------------------------------------------------------------- #
# Grounding: turn the user's answers into real computed numbers (no LLM yet)
# --------------------------------------------------------------------------- #
def _property_context(data: dict, answers: dict) -> dict:
    regions = data["regions"]
    tier = answers["budget"]
    anchor = answers["anchor"]
    priority = answers["priority"]
    w_momentum, w_tourism = PROPERTY_PRIORITIES[priority]
    exclude_prishtina = tier == "Under a threshold"

    ranking = compute_property_ranking(regions, anchor, w_momentum, w_tourism, exclude_prishtina)
    top = ranking[:3]
    lines = [
        f"- {r['name']}: personalized score {r['personalizedScore']:.1f}/100, "
        f"momentum {r['momentumScore']:.1f}/100, investment-share YoY change "
        f"{r['investment_yoy_pct']:+.1f}pp, tourism gap score {r['tourism_gap_score']:.2f}/1, "
        f"{r['distance_km']:.0f} km from {anchor}"
        for r in top
    ]
    header = (
        f"User is looking to buy property. Priority: {priority}. "
        f"Budget tier: {tier}. Anchor point: {anchor}."
    )
    return {"header": header, "lines": lines, "empty": not top}


def _business_context(data: dict, answers: dict) -> dict:
    regions = data["regions"]
    sector = next(s for s in data["business_sectors"] if s["code"] == answers["sector_code"])
    risk = answers["risk"]

    ranked = ranked_business(sector, regions)[:3]
    lines = [
        f"- {name}: score {info['score']:.1f}/100, growth {info['growth_pct']:+.1f}% YoY, "
        f"{info['count_latest']} enterprises latest quarter"
        + (" (low confidence — small base)" if info["low_confidence"] else "")
        for name, info in ranked
    ]
    header = (
        f"User is looking to invest in a business. Sector: {sector['name']} "
        f"({sector['code']}). Risk preference: {risk}."
    )
    return {"header": header, "lines": lines, "empty": not ranked}


def synthesize(context: dict, notes: str) -> str:
    facts = context["header"] + "\n" + "\n".join(context["lines"])
    user_content = facts
    if notes:
        user_content += f'\n\nAnything else the user added: "{notes}"'

    result = call_ollama(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
    )
    if result:
        return result

    note_line = f' You also mentioned: "{notes}".' if notes else ""
    return (
        f"{context['header']}\n\n" + "\n".join(context["lines"]) + "\n\n"
        f"{note_line} This is a screening signal from public statistics only — "
        "a starting point for research, not financial advice, and it doesn't "
        "replace real due diligence."
    ).strip()


# --------------------------------------------------------------------------- #
# Chat state machine (Streamlit session_state)
# --------------------------------------------------------------------------- #
def _key(name: str) -> str:
    return f"{STATE_PREFIX}{name}"


def _init_state() -> None:
    if _key("active") not in st.session_state:
        st.session_state[_key("active")] = False
        st.session_state[_key("step")] = "purpose"
        st.session_state[_key("answers")] = {}
        st.session_state[_key("history")] = []
        st.session_state[_key("result")] = None


def _reset() -> None:
    st.session_state[_key("step")] = "purpose"
    st.session_state[_key("answers")] = {}
    st.session_state[_key("history")] = [{"role": "assistant", "content": _QUESTIONS["purpose"]}]
    st.session_state[_key("result")] = None


def _say(role: str, content: str) -> None:
    st.session_state[_key("history")].append({"role": role, "content": content})


def _goto(step: str) -> None:
    st.session_state[_key("step")] = step
    question = _QUESTIONS.get(step)
    if question:
        _say("assistant", question)


_QUESTIONS = {
    "purpose": (
        "Hi! I'm the AI advisor for this screener. First — are you looking to "
        "**buy property**, or **invest in a business**?"
    ),
    "budget": "Got it — property. What market segment fits your budget?",
    "anchor": "Where in Kosovo do you have ties, or want to be close to (e.g. family, work)?",
    "priority": "What matters more to you for the region?",
    "property_notes": "Anything else about what you're looking for? (Optional.)",
    "sector": "Got it — business. Which sector are you interested in?",
    "risk": "Are you more drawn to fast-growing but higher-risk opportunities, or stable, lower-risk ones?",
    "business_notes": "Anything else about what you're looking for? (Optional.)",
}


def render(data: dict) -> None:
    _init_state()

    if st.button("🤖 AI Summary — ask the advisor", key=_key("open_btn")):
        if not st.session_state[_key("active")]:
            st.session_state[_key("active")] = True
            _reset()
            st.rerun()

    if not st.session_state[_key("active")]:
        return

    with st.container(border=True):
        top = st.columns([6, 1])
        top[0].markdown("**AI advisor**")
        if top[1].button("✖", key=_key("close_btn"), help="Close"):
            st.session_state[_key("active")] = False
            st.rerun()

        for msg in st.session_state[_key("history")]:
            st.chat_message(msg["role"]).write(msg["content"])

        step = st.session_state[_key("step")]
        answers = st.session_state[_key("answers")]

        if step == "purpose":
            c1, c2 = st.columns(2)
            if c1.button("🏠 Buy property", key=_key("purpose_property")):
                _say("user", "Buy property")
                _goto("budget")
                st.rerun()
            if c2.button("🏢 Invest in a business", key=_key("purpose_business")):
                _say("user", "Invest in a business")
                _goto("sector")
                st.rerun()

        elif step == "budget":
            for tier in BUDGET_TIERS:
                if st.button(tier, key=_key(f"budget_{tier}")):
                    answers["budget"] = tier
                    _say("user", tier)
                    _goto("anchor")
                    st.rerun()

        elif step == "anchor":
            region_names = [r["name"] for r in data["regions"]]
            with st.form(key=_key("anchor_form")):
                anchor = st.selectbox("Anchor region", region_names)
                if st.form_submit_button("Continue"):
                    answers["anchor"] = anchor
                    _say("user", anchor)
                    _goto("priority")
                    st.rerun()

        elif step == "priority":
            for label in PROPERTY_PRIORITIES:
                if st.button(label, key=_key(f"priority_{label}")):
                    answers["priority"] = label
                    _say("user", label)
                    _goto("property_notes")
                    st.rerun()

        elif step == "property_notes":
            with st.form(key=_key("property_notes_form")):
                notes = st.text_input("Anything else? (optional)")
                c1, c2 = st.columns(2)
                submit = c1.form_submit_button("Continue")
                skip = c2.form_submit_button("Skip")
                if submit or skip:
                    text = notes if submit else ""
                    if text:
                        _say("user", text)
                    answers["notes"] = text
                    st.session_state[_key("step")] = "done"
                    st.rerun()

        elif step == "sector":
            for sector in data["business_sectors"]:
                label = f"{sector['code']} — {sector['name']}"
                if st.button(label, key=_key(f"sector_{sector['code']}")):
                    answers["sector_code"] = sector["code"]
                    _say("user", label)
                    _goto("risk")
                    st.rerun()

        elif step == "risk":
            for label in RISK_PREFERENCES:
                if st.button(label, key=_key(f"risk_{label}")):
                    answers["risk"] = label
                    _say("user", label)
                    _goto("business_notes")
                    st.rerun()

        elif step == "business_notes":
            with st.form(key=_key("business_notes_form")):
                notes = st.text_input("Anything else? (optional)")
                c1, c2 = st.columns(2)
                submit = c1.form_submit_button("Continue")
                skip = c2.form_submit_button("Skip")
                if submit or skip:
                    text = notes if submit else ""
                    if text:
                        _say("user", text)
                    answers["notes"] = text
                    st.session_state[_key("step")] = "done"
                    st.rerun()

        elif step == "done":
            if st.session_state[_key("result")] is None:
                is_property = "budget" in answers
                context = (
                    _property_context(data, answers)
                    if is_property
                    else _business_context(data, answers)
                )
                if context["empty"]:
                    result = "I couldn't find any matching data for that combination — try different answers."
                else:
                    with st.spinner("Thinking..."):
                        result = synthesize(context, answers.get("notes", ""))
                st.session_state[_key("result")] = result
                _say("assistant", result)
                st.rerun()
            else:
                if st.button("🔄 Start over", key=_key("restart_btn")):
                    _reset()
                    st.rerun()
