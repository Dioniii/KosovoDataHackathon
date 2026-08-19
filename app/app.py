"""Kosovo Property & Investment Screener — Streamlit app.

Run with: streamlit run app.py   (from inside the app/ directory)

This file is the presentation layer only. All scoring/geometry lives in
scoring.py and all data loading in data_loader.py — this module just arranges
and styles them. It works whether scoring.py returns the plain frontend rows or
the richer analysis rows (extra fields like `score` / `low_confidence` are read
defensively with .get()).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_advisor
from data_loader import load_data
from forecast import URGENCY_LABELS, attach_urgency, urgency_note
from scoring import (
    business_trend_points,
    compute_property_ranking,
    rank_business,
    rank_colors,
)

# --------------------------------------------------------------------------- #
# Palette (from the validated design-system reference)
# --------------------------------------------------------------------------- #
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SURFACE = "#fcfcfb"
PLANE = "#f9f9f7"
ACCENT = "#2a78d6"
GOOD = "#006300"
WARNING = "#b06a00"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

st.set_page_config(
    page_title="Kosovo Investment Screener",
    page_icon="📍",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# --------------------------------------------------------------------------- #
# Global styling — one small CSS system, injected once
# --------------------------------------------------------------------------- #
def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
            --ink:{INK}; --ink2:{INK_2}; --muted:{MUTED};
            --surface:{SURFACE}; --plane:{PLANE}; --accent:{ACCENT};
            --border: rgba(11,11,11,0.10);
        }}
        html, body, [class*="css"] {{ font-family:{FONT}; }}

        .block-container {{ max-width: 1180px; padding-top: 2rem; padding-bottom: 4rem; }}

        /* Hero as a card (the extra design block) */
        .hero {{
            position:relative; overflow:hidden;
            background: linear-gradient(135deg,#123a66 0%,#1c5cab 55%,#2a78d6 100%);
            border-radius:18px; padding:1.6rem 1.7rem; color:#fff;
            box-shadow:0 10px 30px -14px rgba(18,58,102,.55);
        }}
        .hero::after {{  /* decorative square, rotated */
            content:""; position:absolute; right:-46px; top:-46px; width:150px; height:150px;
            background:rgba(255,255,255,.08); border-radius:26px; transform:rotate(18deg);
        }}
        .hero h1 {{ font-size: clamp(1.5rem,2.6vw,2.2rem); font-weight:750;
            letter-spacing:-0.02em; margin:0 0 .4rem 0; line-height:1.14; color:#fff; }}
        .hero .sub {{ color:rgba(255,255,255,.9); font-size:1rem; max-width:62ch; }}

        /* Disclaimer — calm, no loud icon */
        .disclaimer {{
            background:#fbf6ea; border:1px solid rgba(176,106,0,.25);
            border-left:4px solid {WARNING}; border-radius:10px;
            padding:.65rem .9rem; margin:.9rem 0 .3rem 0; color:#5b4a1f; font-size:.9rem;
        }}
        .disclaimer b {{ color:#4a3c17; }}
        .disclaimer .tag {{ font-size:.68rem; font-weight:800; letter-spacing:.06em;
            color:{WARNING}; text-transform:uppercase; margin-right:.5rem; }}

        /* KPI stat tiles — hover lift */
        div[data-testid="stMetric"] {{
            background: var(--surface); border:1px solid var(--border);
            border-radius:14px; padding:.85rem 1rem;
            transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
        }}
        div[data-testid="stMetric"]:hover {{
            transform: translateY(-3px); border-color: rgba(42,120,214,.35);
            box-shadow: 0 12px 24px -16px rgba(11,11,11,.4);
        }}
        div[data-testid="stMetricLabel"] p {{ color: var(--muted); font-weight:600;
            font-size:.78rem; text-transform:uppercase; letter-spacing:.04em; }}
        div[data-testid="stMetricValue"] {{ color: var(--ink); font-weight:750; }}

        /* Tabs */
        div[data-baseweb="tab-list"] {{ gap:.4rem; border-bottom:1px solid var(--border); }}
        button[data-baseweb="tab"] {{
            font-size:1rem; font-weight:650; padding:.55rem 1.1rem; border-radius:10px 10px 0 0;
            transition: background .15s ease;
        }}
        button[data-baseweb="tab"]:hover {{ background: rgba(42,120,214,.07); }}
        button[data-baseweb="tab"][aria-selected="true"] {{ color: var(--accent); }}

        h2, h3 {{ letter-spacing:-0.01em; }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius:14px; transition: box-shadow .15s ease; }}
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
            box-shadow:0 10px 26px -18px rgba(11,11,11,.35); }}
        div[data-testid="stDataFrame"] {{ border-radius:12px; overflow:hidden; }}

        /* Podium of square cards (top 3) — interactive hover */
        .podium {{ display:flex; gap:.7rem; margin:.4rem 0 1.1rem 0; flex-wrap:wrap; }}
        .pcard {{
            flex:1 1 160px; min-width:150px; aspect-ratio: 1 / .78;
            border-radius:16px; padding:.9rem 1rem; border:1px solid var(--border);
            background: var(--surface); display:flex; flex-direction:column; justify-content:space-between;
            cursor:default; transition: transform .16s ease, box-shadow .16s ease;
        }}
        .pcard:hover {{ transform: translateY(-4px) scale(1.015);
            box-shadow:0 16px 30px -18px rgba(11,11,11,.45); }}
        .pcard.p1 {{ background: linear-gradient(160deg,#eaf2fd,#dcebfb); border-color:rgba(42,120,214,.35); }}
        .pcard .rk {{ width:30px; height:30px; border-radius:9px; display:flex; align-items:center;
            justify-content:center; font-weight:800; font-size:.95rem; color:#fff; background:var(--accent); }}
        .pcard.p1 .rk {{ background:#123a66; }}
        .pcard .nm {{ font-size:1.08rem; font-weight:750; color:var(--ink); margin-top:.35rem; }}
        .pcard .sc {{ font-size:.86rem; color:var(--ink2); }}
        .pcard .meter {{ height:7px; border-radius:99px; background:#e7ebf2; overflow:hidden; margin-top:.5rem; }}
        .pcard .meter > span {{ display:block; height:100%; border-radius:99px;
            background:linear-gradient(90deg,#5598e7,#184f95); }}

        .badge {{ display:inline-block; font-size:.72rem; font-weight:700; padding:.12rem .5rem;
            border-radius:999px; background:#fbf1dd; color:{WARNING}; border:1px solid rgba(176,106,0,.3);
            margin-left:.4rem; vertical-align:middle; }}

        .urgency {{ display:inline-block; font-size:.72rem; font-weight:700; padding:.12rem .55rem;
            border-radius:999px; margin-left:.4rem; vertical-align:middle; border:1px solid transparent; }}
        .urgency.high {{ background:#fdeae7; color:#a3341f; border-color:rgba(163,52,31,.3); }}
        .urgency.medium {{ background:#fbf1dd; color:{WARNING}; border-color:rgba(176,106,0,.3); }}
        .urgency.low {{ background:#e9f5ea; color:{GOOD}; border-color:rgba(0,99,0,.25); }}
        .urgency.watch {{ background:#eceae4; color:{INK_2}; border-color:rgba(11,11,11,.15); }}

        @media (max-width: 640px) {{
            .block-container {{ padding-top:1.2rem; }}
            .hero {{ padding:1.2rem 1.2rem; }}
            .hero .sub {{ font-size:.94rem; }}
            .pcard {{ flex:1 1 100%; aspect-ratio:auto; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def podium(items: list[dict]) -> None:
    """Render up to 3 square hover-cards. Each item: {name, value, pct}."""
    cards = []
    for i, it in enumerate(items[:3], start=1):
        pct = max(4, min(100, it["pct"]))
        cards.append(
            f'<div class="pcard p{i}"><div class="rk">{i}</div>'
            f'<div><div class="nm">{it["name"]}</div>'
            f'<div class="sc">{it["value"]}</div>'
            f'<div class="meter"><span style="width:{pct:.0f}%"></span></div></div></div>'
        )
    st.markdown(f'<div class="podium">{"".join(cards)}</div>', unsafe_allow_html=True)


def _supports_row_select() -> bool:
    """st.dataframe(on_select=...) row selection needs Streamlit >= 1.35."""
    try:
        major, minor = (int(p) for p in st.__version__.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (1, 35)


SUPPORTS_ROW_SELECT = _supports_row_select()

_BASE_LAYOUT = dict(
    font=dict(family=FONT, color=INK_2, size=13),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=8, r=16, t=8, b=8),
    hoverlabel=dict(bgcolor=INK, font=dict(color="#ffffff", family=FONT, size=12), bordercolor=INK),
)


def _round_bars(fig: go.Figure) -> None:
    """Best-effort 4px rounded data-ends; silently skipped on older Plotly."""
    for setter in (lambda: fig.update_traces(marker_cornerradius=4),
                   lambda: fig.update_layout(barcornerradius=4)):
        try:
            setter()
            return
        except Exception:  # noqa: BLE001
            continue


def build_rank_chart(names: list[str], values: list[float], axis_title: str, suffix: str = "") -> go.Figure:
    """Horizontal bars, one blue ramp keyed to rank (lightest = lowest). One
    measure ranked, so shades of a single hue — never one color per bar."""
    pairs = sorted(zip(names, values), key=lambda p: p[1])  # ascending -> bottom to top
    colors = rank_colors(len(pairs))
    ys = [n for n, _ in pairs]
    xs = [v for _, v in pairs]
    fig = go.Figure(
        go.Bar(
            x=xs, y=ys, orientation="h",
            marker=dict(color=colors, line=dict(width=0)),
            text=[f"{v:.1f}{suffix}" for v in xs],
            textposition="outside", textfont=dict(color=INK_2, family=FONT, size=12),
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>" + axis_title + ": %{x:.1f}" + suffix + "<extra></extra>",
        )
    )
    fig.update_layout(
        **_BASE_LAYOUT,
        xaxis=dict(title=axis_title, gridcolor=GRID, zeroline=False,
                   tickcolor=BASELINE, tickfont=dict(color=MUTED), showline=False),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color=INK, size=13),
                   linecolor=BASELINE),
        height=max(300, 40 * len(pairs)),
        bargap=0.28,
    )
    _round_bars(fig)
    return fig


def select_row(df: pd.DataFrame, name_col: str, key: str) -> str:
    """Row-select on the ranked table if supported, else a plain selectbox."""
    if SUPPORTS_ROW_SELECT:
        event = st.dataframe(
            df, hide_index=True, on_select="rerun",
            selection_mode="single-row", key=key, use_container_width=True,
        )
        rows = event["selection"]["rows"] if event else []
        row = rows[0] if rows else 0
        return df.iloc[row][name_col]
    st.dataframe(df, hide_index=True, use_container_width=True)
    return st.selectbox("Pick a row to inspect", df[name_col].tolist(), key=f"{key}_select")


def urgency_badge_html(tier: str) -> str:
    return f'<span class="urgency {tier}">{URGENCY_LABELS.get(tier, tier)}</span>'


def build_trend_chart(points: list[tuple[str, float]], y_title: str) -> go.Figure:
    labels = [p[0] for p in points]
    values = [p[1] for p in points]
    fig = go.Figure(
        go.Scatter(
            x=labels, y=values, mode="lines+markers",
            line=dict(color=ACCENT, width=2.5, shape="spline"),
            marker=dict(size=10, color=ACCENT, line=dict(color=SURFACE, width=2)),
            fill="tozeroy", fillcolor="rgba(42,120,214,0.08)",
            hovertemplate="%{x}<br>" + y_title + ": %{y:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        **_BASE_LAYOUT,
        xaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color=INK)),
        yaxis=dict(title=y_title, gridcolor=GRID, zeroline=False,
                   tickfont=dict(color=MUTED), rangemode="tozero"),
        height=270, hovermode="x unified",
    )
    return fig


def brief_card(text: str, empty_msg: str) -> None:
    with st.container(border=True):
        st.markdown("**Research brief**")
        st.write(text if text else f"_{empty_msg}_")


def view_toggle(key: str) -> str:
    """Interactive Chart/Table switch, using segmented_control when available."""
    if hasattr(st, "segmented_control"):
        return st.segmented_control("View", ["Chart", "Table"], default="Chart",
                                    key=key, label_visibility="collapsed") or "Chart"
    return st.radio("View", ["Chart", "Table"], horizontal=True,
                    key=key, label_visibility="collapsed")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
inject_css()

data = load_data()
regions = data["regions"]
housing = data["housing"]
business_sectors = data["business_sectors"]
insights = data.get("insights", {})
national = data.get("national", {})

st.markdown(
    """
    <div class="hero">
      <h1>Kosovo Property &amp; Investment Screener</h1>
      <div class="sub">Find which region of Kosovo is worth a closer look — for buying
      property, or investing in a business — using official open statistics.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

ai_advisor.render(data)

st.markdown(
    """
    <div class="disclaimer">
      <span class="tag">Note</span>
      <b>Not investment advice.</b> This is a screening tool that ranks regions from
      public statistics as a starting point for research — not a recommendation to buy or invest.
    </div>
    """,
    unsafe_allow_html=True,
)

if national:
    k1, k2, k3 = st.columns(3)
    k1.metric("GDP growth", f"{national.get('gdp_growth_pct', '—')}%")
    k2.metric("FDI (% of GDP)", f"{national.get('fdi_pct_gdp', '—')}%")
    k3.metric("Data updated", str(national.get("last_updated", "—")))

st.write("")
tab_property, tab_business = st.tabs(["Buy property", "Invest in a business"])

# --------------------------------------------------------------------------- #
# PROPERTY
# --------------------------------------------------------------------------- #
with tab_property:
    st.subheader("Which region is worth researching for a property purchase?")

    col1, col2 = st.columns(2)
    with col1:
        budget_tier = st.select_slider(
            "Market segment (price-index tier)",
            options=["Under a threshold", "Around it", "Above it"],
            value="Around it",
            help="We only have a relative price index, not euro prices — this picks "
                 "which market segment is realistic for you.",
        )
    with col2:
        region_names = [r["name"] for r in regions]
        default_anchor = "Prishtinë" if "Prishtinë" in region_names else region_names[0]
        anchor_name = st.selectbox(
            "Your anchor point (e.g. where you have family)",
            region_names, index=region_names.index(default_anchor),
        )

    with st.expander("Adjust what matters to you", expanded=True):
        wcol1, wcol2 = st.columns(2)
        with wcol1:
            w_momentum = st.slider("Weight: investment momentum", 0.0, 1.0, 0.5, 0.05)
        with wcol2:
            w_tourism = st.slider("Weight: tourism demand", 0.0, 1.0, 0.5, 0.05)

    exclude_prishtina = budget_tier == "Under a threshold"
    if exclude_prishtina:
        st.caption("Lower-tier segment selected — Prishtinë (highest price index) is excluded.")

    ranking = compute_property_ranking(regions, anchor_name, w_momentum, w_tourism, exclude_prishtina)
    ranking = attach_urgency(ranking, housing)

    if not ranking:
        st.warning("No regions to rank with the current filters.")
    else:
        st.markdown("#### Top picks for your inputs")
        podium([{
            "name": r["name"],
            "value": (
                f"score {r['personalizedScore']:.1f}/100"
                + (urgency_badge_html(r["forecast"]["urgency"]) if r["forecast"] else "")
            ),
            "pct": r["personalizedScore"],
        } for r in ranking])
        if any(r["forecast"] and r["forecast"]["urgency"] == "high" for r in ranking):
            st.caption(
                "🔥 **High urgency** = our 1-year price forecast for that segment is "
                "trending up fast. Select a region below for the full note."
            )

        left, right = st.columns([3, 1])
        left.markdown("**Full ranking**")
        with right:
            pview = view_toggle("property_view")

        if pview == "Chart":
            st.plotly_chart(
                build_rank_chart([r["name"] for r in ranking],
                                 [r["personalizedScore"] for r in ranking], "Personalized score"),
                use_container_width=True, key="property_chart",
            )

        table_rows = [
            {
                "name": r["name"],
                "personalizedScore": r["personalizedScore"],
                "momentumScore": r["momentumScore"],
                "investment_yoy_pct": r["investment_yoy_pct"],
                "tourism_gap_score": r["tourism_gap_score"],
                "distance_km": r["distance_km"],
                "predicted_yoy_pct": r["forecast"]["predicted_yoy_pct"] if r["forecast"] else None,
                "urgency": URGENCY_LABELS.get(r["forecast"]["urgency"], "—") if r["forecast"] else "—",
            }
            for r in ranking
        ]
        table_df = pd.DataFrame(table_rows).round(2)
        table_df.columns = ["Region", "Personalized score", "Momentum score",
                            "Investment YoY %", "Tourism gap (0-1)", "Distance (km)",
                            "Predicted price YoY % (1yr)", "Urgency"]

        st.caption("Select a region below to see its price outlook and research brief.")
        selected_name = select_row(table_df, "Region", key="property_table")
        detail = next(r for r in ranking if r["name"] == selected_name)
        region_obj = next(r for r in regions if r["name"] == selected_name)
        forecast = detail["forecast"]

        badge_html = urgency_badge_html(forecast["urgency"]) if forecast else ""
        st.markdown(f"### {selected_name}{badge_html}", unsafe_allow_html=True)
        avg_score = sum(r["personalizedScore"] for r in ranking) / len(ranking)
        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("Personalized score", f"{detail['personalizedScore']:.1f}",
                     delta=f"{detail['personalizedScore'] - avg_score:+.1f} vs. shown avg")
        mcol2.metric("Investment (construction share) YoY", f"{detail['investment_yoy_pct']:.1f} pts")
        if forecast:
            mcol3.metric("Predicted price index (1yr)", f"{forecast['predicted_index']:.1f}",
                         delta=f"{forecast['predicted_yoy_pct']:+.1f}% vs. now")
        else:
            mcol3.metric("Predicted price index (1yr)", "—")

        c_urgency, c_brief = st.columns([1, 1])
        with c_urgency:
            with st.container(border=True):
                st.markdown("**Price outlook**")
                st.markdown(urgency_note(forecast, region_obj["housing_bucket"]))
                if forecast:
                    st.caption(
                        f"Linear trend fit on quarterly price history, fit quality "
                        f"R²={forecast['r_squared']:.2f}. A screening signal, not a valuation."
                    )
        with c_brief:
            brief_card(insights.get(selected_name, ""), "No research brief yet for this region.")

# --------------------------------------------------------------------------- #
# BUSINESS
# --------------------------------------------------------------------------- #
with tab_business:
    st.subheader("Which municipality is worth researching for a business investment?")

    sector_labels = [f"{s['code']} — {s['name']}" for s in business_sectors]
    default_index = next((i for i, s in enumerate(business_sectors) if s["code"] == "I"), 0)
    sector_choice = st.selectbox("Business sector", sector_labels, index=default_index)
    sector = business_sectors[sector_labels.index(sector_choice)]

    biz_ranking = rank_business(sector)

    if not biz_ranking:
        st.warning("No municipality data for this sector.")
    else:
        low_conf_any = any(r.get("low_confidence") for r in biz_ranking)
        if low_conf_any:
            hide_small = st.toggle("Hide small-base municipalities", value=False,
                                   help="Very few registered businesses make growth % swing on "
                                        "just a handful of registrations.")
            if hide_small:
                filtered = [r for r in biz_ranking if not r.get("low_confidence")]
                biz_ranking = filtered or biz_ranking

        # podium of top 3 municipalities (meter scaled across shown growth values)
        gvals = [r["growth_pct"] for r in biz_ranking]
        gmin, gmax = min(gvals), max(gvals)
        span = (gmax - gmin) or 1
        st.markdown("#### Top picks in this sector")
        podium([{"name": r["name"], "value": f"{r['growth_pct']:+.1f}% growth",
                 "pct": (r["growth_pct"] - gmin) / span * 100} for r in biz_ranking])

        left, right = st.columns([3, 1])
        left.markdown("**Full ranking**")
        with right:
            bview = view_toggle("business_view")
        if bview == "Chart":
            st.plotly_chart(
                build_rank_chart([r["name"] for r in biz_ranking],
                                 [r["growth_pct"] for r in biz_ranking], "Growth %", suffix="%"),
                use_container_width=True, key="business_chart",
            )

        cols = ["name", "growth_pct", "count_latest"]
        rename = {"name": "Municipality", "growth_pct": "Growth %", "count_latest": "Enterprises (latest)"}
        if any("low_confidence" in r for r in biz_ranking):
            for r in biz_ranking:
                r["Small base?"] = "yes" if r.get("low_confidence") else "—"
            cols.append("Small base?")
            rename["Small base?"] = "Small base?"
        table_df = pd.DataFrame(biz_ranking)[cols].round(2).rename(columns=rename)

        st.caption("Select a municipality below to see its trend and research brief.")
        selected_muni = select_row(table_df, "Municipality", key="business_table")
        entry = sector["by_municipality"][selected_muni]

        badge = ""
        row = next((r for r in biz_ranking if r["name"] == selected_muni), {})
        if row.get("low_confidence"):
            badge = ' <span class="badge">small base — read with care</span>'
        st.markdown(f"### {selected_muni} — {sector['name']}{badge}", unsafe_allow_html=True)

        mcol1, mcol2 = st.columns(2)
        mcol1.metric("Growth %", f"{entry['growth_pct']:.1f}%", delta=f"{entry['growth_pct']:.1f}%")
        mcol2.metric("Enterprises (latest)", f"{entry['count_latest']:.0f}")

        c_chart, c_brief = st.columns([1, 1])
        with c_chart:
            st.plotly_chart(
                build_trend_chart(business_trend_points(entry), "Enterprise count"),
                use_container_width=True, key="business_trend",
            )
        with c_brief:
            brief_card(insights.get(f"sector:{sector['code']}:{selected_muni}", ""),
                       "No research brief yet for this municipality/sector.")
