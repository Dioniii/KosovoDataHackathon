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


# CSS for the floating widget. "__PFX__" is replaced with STATE_PREFIX so the
# selectors always match the st.container(key=...) classes below regardless
# of what STATE_PREFIX is set to. Colors are the app's own palette (primary
# blue from .streamlit/config.toml, the #F43F5E accent and violet/sky tones
# already used for charts in app.py) so the widget reads as part of the app,
# not a bolted-on component.
_CSS = """
<style>
.st-key-__PFX__fab_wrap {
    position: fixed;
    right: 24px;
    bottom: 24px;
    z-index: 999995;
    width: 60px;
}
.st-key-__PFX__fab_wrap button {
    width: 60px;
    height: 60px;
    border-radius: 50% !important;
    border: none !important;
    background: linear-gradient(135deg, #38BDF8, #2a78d6 55%, #8B5CF6) !important;
    color: #ffffff !important;
    font-size: 1.4rem !important;
    box-shadow: 0 10px 26px rgba(42, 120, 214, 0.4);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    animation: adv-pulse 2.6s ease-in-out infinite;
}
.st-key-__PFX__fab_wrap button:hover {
    transform: scale(1.08) rotate(3deg);
    box-shadow: 0 12px 30px rgba(42, 120, 214, 0.5);
}
.st-key-__PFX__fab_wrap button:active { transform: scale(0.94); }
.st-key-__PFX__fab_wrap button p { font-size: 1.4rem !important; }

@keyframes adv-pulse {
    0%, 100% { box-shadow: 0 10px 26px rgba(42, 120, 214, 0.4), 0 0 0 0 rgba(139, 92, 246, 0.35); }
    50% { box-shadow: 0 10px 30px rgba(42, 120, 214, 0.5), 0 0 0 9px rgba(139, 92, 246, 0); }
}

.st-key-__PFX__panel_wrap {
    position: fixed;
    right: 24px;
    bottom: 96px;
    z-index: 999994;
    width: 380px;
    max-width: calc(100vw - 32px);
    max-height: min(600px, calc(100vh - 140px));
    background: #ffffff;
    border: 1px solid #E2E8F0;
    border-radius: 18px;
    box-shadow: 0 24px 60px rgba(15, 23, 42, 0.22), 0 2px 10px rgba(15, 23, 42, 0.08);
    overflow: hidden;
    animation: adv-panel-in 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes adv-panel-in {
    from { opacity: 0; transform: translateY(18px) scale(0.95); }
    to { opacity: 1; transform: translateY(0) scale(1); }
}

.st-key-__PFX__header {
    background: linear-gradient(120deg, #2a78d6, #8B5CF6);
    padding: 0.85rem 1rem 0.7rem;
}
.st-key-__PFX__header button {
    background: rgba(255, 255, 255, 0.18) !important;
    border: none !important;
    color: #ffffff !important;
    border-radius: 50% !important;
    width: 30px;
    height: 30px;
}
.st-key-__PFX__header button:hover { background: rgba(255, 255, 255, 0.3) !important; }
.adv-title {
    color: #ffffff;
    font-weight: 700;
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}
.adv-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #4ADE80;
    box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.6);
    animation: adv-dot-ping 2s ease-in-out infinite;
    display: inline-block;
}
@keyframes adv-dot-ping {
    0%, 100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.6); }
    50% { box-shadow: 0 0 0 4px rgba(74, 222, 128, 0); }
}
.adv-sub {
    color: rgba(255, 255, 255, 0.85);
    font-size: 0.75rem;
    margin-top: 0.1rem;
}

.st-key-__PFX__messages { background: #ffffff; padding: 0.25rem 0.15rem; }
.st-key-__PFX__messages [data-testid="stChatMessage"]:last-child {
    animation: adv-msg-in 0.25s ease;
}
@keyframes adv-msg-in {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
}

.st-key-__PFX__input_area {
    background: #FAFAF9;
    border-top: 1px solid #E2E8F0;
    padding: 0.7rem 0.85rem 0.85rem;
}
.st-key-__PFX__input_area button {
    border-radius: 999px !important;
    font-size: 0.85rem !important;
}
.st-key-__PFX__input_area [data-testid="stForm"] {
    border: none;
    padding: 0;
}

.adv-typing {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 0.5rem 0.75rem;
    background: #F1F5F9;
    border-radius: 999px;
    margin-bottom: 0.4rem;
}
.adv-typing span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #8B5CF6;
    animation: adv-bounce 1.1s infinite ease-in-out;
}
.adv-typing span:nth-child(2) { animation-delay: 0.15s; }
.adv-typing span:nth-child(3) { animation-delay: 0.3s; }
@keyframes adv-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
    30% { transform: translateY(-4px); opacity: 1; }
}

@media (max-width: 480px) {
    .st-key-__PFX__fab_wrap {
        right: max(12px, env(safe-area-inset-right));
        bottom: max(12px, env(safe-area-inset-bottom));
        width: 54px;
    }
    .st-key-__PFX__fab_wrap button {
        width: 54px;
        height: 54px;
        min-height: 54px;
    }
    .st-key-__PFX__panel_wrap {
        right: max(8px, env(safe-area-inset-right));
        left: max(8px, env(safe-area-inset-left));
        width: auto;
        max-width: none;
        bottom: calc(76px + env(safe-area-inset-bottom));
        max-height: calc(100dvh - 92px - env(safe-area-inset-top) - env(safe-area-inset-bottom));
        border-radius: 16px;
        overflow-x: hidden;
        overflow-y: auto;
        overscroll-behavior: contain;
        -webkit-overflow-scrolling: touch;
    }
    .st-key-__PFX__header {
        position: sticky;
        top: 0;
        z-index: 3;
        padding: 0.7rem 0.75rem 0.6rem;
    }
    .adv-title { font-size: 0.95rem; }
    .adv-sub {
        max-width: 78vw;
        font-size: 0.68rem;
        line-height: 1.25;
    }
    .st-key-__PFX__messages {
        height: clamp(170px, 38dvh, 280px) !important;
        min-height: 170px;
        padding: 0.15rem 0;
        overflow-x: hidden;
        overflow-y: auto;
    }
    .st-key-__PFX__messages [data-testid="stChatMessage"] {
        padding: 0.65rem 0.6rem;
    }
    .st-key-__PFX__messages [data-testid="stChatMessage"] p {
        overflow-wrap: anywhere;
        word-break: normal;
    }
    .st-key-__PFX__input_area {
        position: sticky;
        bottom: 0;
        z-index: 3;
        padding: 0.55rem 0.65rem calc(0.65rem + env(safe-area-inset-bottom));
    }
    .st-key-__PFX__input_area [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
        gap: 0.45rem;
    }
    .st-key-__PFX__input_area :is([data-testid="stColumn"], [data-testid="column"]) {
        flex: 1 1 100% !important;
        width: 100% !important;
        min-width: 100% !important;
    }
    .st-key-__PFX__input_area button {
        min-height: 44px;
        white-space: normal;
        line-height: 1.2;
    }
}

@media (max-width: 360px) {
    .st-key-__PFX__panel_wrap {
        right: max(4px, env(safe-area-inset-right));
        left: max(4px, env(safe-area-inset-left));
        border-radius: 13px;
    }
    .st-key-__PFX__messages {
        height: clamp(150px, 34dvh, 230px) !important;
        min-height: 150px;
    }
}
</style>
""".replace("__PFX__", STATE_PREFIX)


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


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
    _inject_css()

    active = st.session_state[_key("active")]

    with st.container(key=_key("fab_wrap")):
        if st.button("×" if active else "AI", key=_key("fab_btn"), help="AI advisor"):
            st.session_state[_key("active")] = not active
            if not active:  # was closed -> just opened: start a fresh intake
                _reset()
            st.rerun()

    if not st.session_state[_key("active")]:
        return

    with st.container(key=_key("panel_wrap")):
        with st.container(key=_key("header")):
            hcol1, hcol2 = st.columns([6, 1], vertical_alignment="center")
            with hcol1:
                st.markdown(
                    '<div class="adv-title">AI advisor <span class="adv-dot"></span></div>'
                    '<div class="adv-sub">Grounded in this app\'s data — not financial advice</div>',
                    unsafe_allow_html=True,
                )
            with hcol2:
                if st.button("×", key=_key("close_btn"), help="Close"):
                    st.session_state[_key("active")] = False
                    st.rerun()

        with st.container(key=_key("messages"), height=340):
            for msg in st.session_state[_key("history")]:
                st.chat_message(msg["role"]).write(msg["content"])

        with st.container(key=_key("input_area")):
            step = st.session_state[_key("step")]
            answers = st.session_state[_key("answers")]

            if step == "purpose":
                c1, c2 = st.columns(2)
                if c1.button("Buy property", key=_key("purpose_property"), width="stretch"):
                    _say("user", "Buy property")
                    _goto("budget")
                    st.rerun()
                if c2.button("Invest in a business", key=_key("purpose_business"), width="stretch"):
                    _say("user", "Invest in a business")
                    _goto("sector")
                    st.rerun()

            elif step == "budget":
                for tier in BUDGET_TIERS:
                    if st.button(tier, key=_key(f"budget_{tier}"), width="stretch"):
                        answers["budget"] = tier
                        _say("user", tier)
                        _goto("anchor")
                        st.rerun()

            elif step == "anchor":
                region_names = [r["name"] for r in data["regions"]]
                with st.form(key=_key("anchor_form")):
                    anchor = st.selectbox("Anchor region", region_names)
                    if st.form_submit_button("Continue", type="primary"):
                        answers["anchor"] = anchor
                        _say("user", anchor)
                        _goto("priority")
                        st.rerun()

            elif step == "priority":
                for label in PROPERTY_PRIORITIES:
                    if st.button(label, key=_key(f"priority_{label}"), width="stretch"):
                        answers["priority"] = label
                        _say("user", label)
                        _goto("property_notes")
                        st.rerun()

            elif step == "property_notes":
                with st.form(key=_key("property_notes_form")):
                    notes = st.text_input("Anything else? (optional)", placeholder="Type here…")
                    c1, c2 = st.columns(2)
                    submit = c1.form_submit_button("Send", type="primary", width="stretch")
                    skip = c2.form_submit_button("Skip", width="stretch")
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
                    if st.button(label, key=_key(f"sector_{sector['code']}"), width="stretch"):
                        answers["sector_code"] = sector["code"]
                        _say("user", label)
                        _goto("risk")
                        st.rerun()

            elif step == "risk":
                for label in RISK_PREFERENCES:
                    if st.button(label, key=_key(f"risk_{label}"), width="stretch"):
                        answers["risk"] = label
                        _say("user", label)
                        _goto("business_notes")
                        st.rerun()

            elif step == "business_notes":
                with st.form(key=_key("business_notes_form")):
                    notes = st.text_input("Anything else? (optional)", placeholder="Type here…")
                    c1, c2 = st.columns(2)
                    submit = c1.form_submit_button("Send", type="primary", width="stretch")
                    skip = c2.form_submit_button("Skip", width="stretch")
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
                        st.markdown(
                            '<div class="adv-typing"><span></span><span></span><span></span></div>',
                            unsafe_allow_html=True,
                        )
                        result = synthesize(context, answers.get("notes", ""))
                    st.session_state[_key("result")] = result
                    _say("assistant", result)
                    st.rerun()
                else:
                    if st.button("Start over", key=_key("restart_btn"), type="primary", width="stretch"):
                        _reset()
                        st.rerun()
