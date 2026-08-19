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
import plotly.io as pio
import streamlit as st

import ai_advisor
from data_loader import load_data
from forecast import URGENCY_LABELS, attach_urgency, urgency_note
from scoring import (
    business_trend_points,
    compute_property_ranking,
    normalize,
    rank_business,
    rank_colors,
)

# Shared typography and text colors used by the Plotly chart styling below.
INK = "#0b0b0b"
INK_2 = "#52514e"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

st.set_page_config(page_title="Kosovo Investment Screener", page_icon=":material/location_city:", layout="wide")

# Custom Plotly template: discrete/qualitative colorway for any chart comparing
# genuinely different series (as opposed to the ranked bar charts below, which
# use scoring.rank_colors' single-hue sequential ramp on purpose — one measure
# ranked, not distinct categories, keeps its own single hue rather than this
# colorway).
pio.templates["kosovo"] = go.layout.Template(
    layout=go.Layout(
        colorway=["#755E62", "#38BDF8", "#8B5CF6", "#10B981"],
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#282C37"),
    )
)
pio.templates.default = "kosovo"

# App-wide polish: gradient hero banner, light metric cards (white fill, pink
# accent value — same #F43F5E brand accent as before, just moved off a dark
# card onto a light one), and the tab underline/label in that same accent.
# st.metric has no per-instance style params, so this targets its stable
# data-testid hooks directly.
st.markdown(
    """
    <style>
    .ks-hero {
        background: linear-gradient(120deg, #1E3A8A 0%, #2a78d6 55%, #38BDF8 130%);
        border-radius: 1rem;
        padding: 1.75rem 2rem;
        margin-bottom: 1.1rem;
        box-shadow: 0 10px 30px rgba(37, 99, 235, 0.18);
    }
    .ks-hero-title {
        color: #ffffff;
        font-size: 1.9rem;
        font-weight: 700;
        letter-spacing: -0.01em;
        margin-bottom: 0.35rem;
    }
    .ks-hero-sub {
        color: rgba(255, 255, 255, 0.88);
        font-size: 1rem;
        max-width: 46rem;
        line-height: 1.45;
    }
    [data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #E2E8F0;
        border-radius: 0.9rem;
        padding: 1rem 1.1rem 0.75rem;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.05);
        transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        box-shadow: 0 10px 26px rgba(15, 23, 42, 0.09);
        transform: translateY(-2px);
    }
    [data-testid="stMetricLabel"] { color: #64748B !important; font-weight: 500; }
    [data-testid="stMetricValue"] { color: #F43F5E !important; font-weight: 700; }
    [data-testid="stTab"][aria-selected="true"] p { color: #F43F5E !important; }
    [data-testid="stTab"] .react-aria-SelectionIndicator { background-color: #F43F5E !important; }
    .podium { display: flex; gap: 0.7rem; margin: 0.4rem 0 1.1rem; flex-wrap: wrap; }
    .pcard {
        flex: 1 1 160px; min-width: 150px; border: 1px solid #E2E8F0;
        border-radius: 0.9rem; padding: 0.9rem 1rem; background: #ffffff;
    }
    .pcard .rk { color: #F43F5E; font-weight: 800; }
    .pcard .nm { color: #0b0b0b; font-size: 1.05rem; font-weight: 700; margin-top: 0.35rem; }
    .pcard .sc { color: #52514e; font-size: 0.86rem; }
    .pcard .meter { height: 7px; border-radius: 99px; background: #E2E8F0; overflow: hidden; margin-top: 0.5rem; }
    .pcard .meter span { display: block; height: 100%; border-radius: 99px; background: #F43F5E; }
    .urgency {
        display: inline-block; margin-left: 0.4rem; padding: 0.12rem 0.55rem;
        border-radius: 999px; background: #F1F5F9; color: #52514e;
        font-size: 0.72rem; font-weight: 700; vertical-align: middle;
    }
    .urgency.high { background: #FEE2E2; color: #991B1B; }
    .urgency.medium { background: #FEF3C7; color: #92400E; }
    .urgency.low { background: #DCFCE7; color: #166534; }
    .urgency.watch { background: #F1F5F9; color: #475569; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _supports_row_select() -> bool:
    """st.dataframe(on_select=...) row selection needs Streamlit >= 1.35."""
    try:
        major, minor = (int(p) for p in st.__version__.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (1, 35)


SUPPORTS_ROW_SELECT = _supports_row_select()


def podium(items: list[dict]) -> None:
    """Render the three highest-ranked items as compact summary cards."""
    cards = []
    for rank, item in enumerate(items[:3], start=1):
        pct = max(4.0, min(100.0, float(item["pct"])))
        cards.append(
            f'<div class="pcard p{rank}"><div class="rk">#{rank}</div>'
            f'<div class="nm">{item["name"]}</div>'
            f'<div class="sc">{item["value"]}</div>'
            f'<div class="meter"><span style="width:{pct:.0f}%"></span></div></div>'
        )
    st.markdown(f'<div class="podium">{"".join(cards)}</div>', unsafe_allow_html=True)


def urgency_badge_html(tier: str) -> str:
    """Return the styled label used beside property forecast results."""
    return f'<span class="urgency {tier}">{URGENCY_LABELS.get(tier, tier)}</span>'


_BASE_LAYOUT = dict(
    font=dict(color=INK_2, size=13),
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
    """Horizontal bar chart, one color ramp keyed to rank: lightest = lowest,
    darkest = highest. This is one measure ranked, not distinct categories,
    so every bar uses shades of the same hue (the theme's primary accent)
    rather than one color each."""
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
        template="kosovo",
        xaxis_title=axis_title,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(320, 34 * len(pairs)),
    )
    _round_bars(fig)
    return fig


def build_trend_chart(points: list[tuple[str, float]], y_title: str) -> go.Figure:
    labels = [p[0] for p in points]
    values = [p[1] for p in points]
    fig = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            line=dict(color="#38BDF8", width=3),
            marker=dict(size=9),
        )
    )
    fig.update_layout(
        template="kosovo",
        yaxis_title=y_title,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
    )
    return fig


def build_region_map(ranking: list[dict], regions: list[dict]) -> go.Figure:
    """Clickable bubble map of the 7 regions, sized/colored by personalizedScore.

    Same single-hue "darkest = best" convention as build_rank_chart, just
    applied by region name instead of by bar position, since markers are
    placed by lat/lon rather than by rank order.
    """
    coords_by_name = {r["name"]: r["coordinates"] for r in regions}
    scores = [r["personalizedScore"] for r in ranking]
    sizes = [18 + 24 * n for n in normalize(scores)]  # 18-42px, always clickable even at score 0
    ramp = rank_colors(len(ranking))  # index 0 = lightest = lowest score
    colors = [ramp[len(ranking) - 1 - i] for i in range(len(ranking))]  # ranking is best-first

    fig = go.Figure(
        go.Scattermap(
            lat=[coords_by_name[r["name"]]["lat"] for r in ranking],
            lon=[coords_by_name[r["name"]]["lon"] for r in ranking],
            mode="markers",
            marker=dict(size=sizes, color=colors),
            text=[r["name"] for r in ranking],
            customdata=scores,
            hovertemplate="<b>%{text}</b><br>Personalized score: %{customdata:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        template="kosovo",
        map=dict(style="carto-positron", center=dict(lat=42.52, lon=20.87), zoom=7.6),
        margin=dict(l=0, r=0, t=0, b=0),
        width=420,
        height=420,
    )
    return fig


def _selection_changed(current: list, remember_key: str) -> bool:
    """True if a widget's on_select payload differs from what we saw last rerun.

    Used to resolve which of two selection sources (ranked table vs. region
    map) the user most recently interacted with — both persist their last
    selection across every rerun regardless of which one actually changed,
    so "whichever is non-empty" isn't enough to tell them apart.
    """
    changed = current != st.session_state.get(remember_key)
    st.session_state[remember_key] = current
    return changed


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
data = load_data()
regions = data["regions"]
housing = data["housing"]
business_sectors = data["business_sectors"]
insights = data.get("insights", {})
national = data.get("national", {})

st.markdown(
    """
    <div class="ks-hero">
      <div class="ks-hero-title">Kosovo Property &amp; Investment Screener</div>
      <div class="ks-hero-sub">Find which region of Kosovo is worth a closer look —
      for buying property, or investing in a business — using official open statistics.</div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.info(
    "**Not investment advice.** This ranks regions using public statistics as a "
    "starting point for research, not a recommendation.",
    icon=":material/info:",
)
if national:
    with st.container(border=True):
        ncol1, ncol2, ncol3 = st.columns(3)
        ncol1.metric("GDP growth", f"{national.get('gdp_growth_pct', '—')}%")
        ncol2.metric("FDI (% of GDP)", f"{national.get('fdi_pct_gdp', '—')}%")
        ncol3.metric("Data as of", f"{national.get('last_updated', '—')}")

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

    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            budget_tier = st.select_slider(
                "Market segment (price index tier)",
                options=["Under a threshold", "Around it", "Above it"],
                value="Around it",
                help=(
                    "We only have a relative price index, not absolute euro prices — "
                    "this picks which market segment is realistic for you."
                ),
            )
        with col2:
            region_names = [r["name"] for r in regions]
            default_anchor = "Prishtinë" if "Prishtinë" in region_names else region_names[0]
            anchor_name = st.selectbox(
                "Your anchor point (e.g. where you have family)",
                region_names,
                index=region_names.index(default_anchor),
            )

        wcol1, wcol2 = st.columns(2)
        with wcol1:
            w_momentum = st.slider("Weight: investment momentum", 0.0, 1.0, 0.5, 0.05)
        with wcol2:
            w_tourism = st.slider("Weight: tourism demand", 0.0, 1.0, 0.5, 0.05)

        exclude_prishtina = budget_tier == "Under a threshold"
        if exclude_prishtina:
            st.caption("Lower-tier segment selected — Prishtinë (highest price index) is excluded from ranking.")

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
            st.caption("🔥 High urgency = prices there are expected to rise a lot in the next year.")

        table_df = pd.DataFrame(ranking)[
            ["name", "personalizedScore", "momentumScore", "investment_yoy_pct", "tourism_gap_score", "distance_km"]
        ].round(2)
        table_df.columns = ["Region", "Personalized score", "Momentum score", "Investment YoY %", "Tourism gap (0-1)", "Distance (km)"]

        if SUPPORTS_ROW_SELECT:
            table_event = st.dataframe(
                table_df, hide_index=True, on_select="rerun", selection_mode="single-row", key="property_table"
            )
        else:
            st.dataframe(table_df, hide_index=True)
            table_event = None

        with st.container(border=True):
            map_col, detail_col = st.columns([1, 1.3])

            with map_col:
                st.caption("Or click a region on the map:")
                map_event = st.plotly_chart(
                    build_region_map(ranking, regions),
                    width=420,
                    height=420,
                    config={"displayModeBar": False},
                    on_select="rerun",
                    selection_mode="points",
                    key="property_map",
                )

            if SUPPORTS_ROW_SELECT:
                table_rows = table_event["selection"]["rows"] if table_event else []
                map_points = map_event["selection"]["points"] if map_event else []
                map_changed = _selection_changed(map_points, "_prev_map_sel")
                table_changed = _selection_changed(table_rows, "_prev_table_sel")

                if map_changed and map_points:
                    selected_name = ranking[map_points[0]["point_index"]]["name"]
                elif table_changed and table_rows:
                    selected_name = table_df.iloc[table_rows[0]]["Region"]
                elif st.session_state.get("property_selected_region") in [r["name"] for r in ranking]:
                    selected_name = st.session_state["property_selected_region"]
                elif table_rows:
                    selected_name = table_df.iloc[table_rows[0]]["Region"]
                else:
                    selected_name = ranking[0]["name"]
                st.session_state["property_selected_region"] = selected_name
            else:
                # No native row-select widget on this Streamlit version — fall back
                # to a plain picker; the map above is still shown, view-only.
                selected_name = st.selectbox("Pick a region to inspect", [r["name"] for r in ranking], key="property_select")

            detail = next(r for r in ranking if r["name"] == selected_name)

            with map_col:
                alert_kind, message = urgency_note(detail.get("forecast"), selected_name)
                getattr(st, alert_kind)(message)

            with detail_col:
                st.markdown(f'<h3 style="color:#F43F5E; margin-top:0;">{selected_name}</h3>', unsafe_allow_html=True)
                avg_score = sum(r["personalizedScore"] for r in ranking) / len(ranking)
                mcol1, mcol2 = st.columns(2)
                mcol1.metric(
                    "Personalized score",
                    f"{detail['personalizedScore']:.1f}",
                    delta=f"{detail['personalizedScore'] - avg_score:+.1f} vs. avg of shown regions",
                )
                mcol2.metric(
                    "Investment YoY",
                    f"{detail['investment_yoy_pct']:.1f}%",
                    delta=f"{detail['investment_yoy_pct']:.1f}%",
                )

                insight_text = insights.get(selected_name, "")
                st.markdown("**Research brief**")
                st.write(insight_text if insight_text else "_No research brief yet for this region._")

with tab_business:
    st.subheader("Which municipality is worth researching for a business investment?")

    with st.container(border=True):
        sector_labels = [f"{s['code']} — {s['name']}" for s in business_sectors]
        default_index = next((i for i, s in enumerate(business_sectors) if s["code"] == "I"), 0)
        sector_choice = st.selectbox("Business sector", sector_labels, index=default_index)
        sector = business_sectors[sector_labels.index(sector_choice)]

    biz_ranking = rank_business(sector)

    if not biz_ranking:
        st.warning("No municipality data for this sector.")
    else:
        with st.container(border=True):
            st.plotly_chart(
                build_rank_chart([r["name"] for r in biz_ranking], [r["growth_pct"] for r in biz_ranking], "Growth %", suffix="%"),
                key="business_chart",
            )

            table_df = pd.DataFrame(biz_ranking)[["name", "growth_pct", "count_latest"]].round(2)
            table_df.columns = ["Municipality", "Growth %", "Enterprises (latest)"]

            selected_muni = select_row(table_df, "Municipality", key="business_table")

        entry = sector["by_municipality"][selected_muni]

        with st.container(border=True):
            st.markdown(
                f'<h3 style="color:#F43F5E; margin-top:0;">{selected_muni} — {sector["name"]}</h3>',
                unsafe_allow_html=True,
            )
            mcol1, mcol2 = st.columns(2)
            mcol1.metric("Growth %", f"{entry['growth_pct']:.1f}%", delta=f"{entry['growth_pct']:.1f}%")
            mcol2.metric("Enterprises (latest)", f"{entry['count_latest']:.0f}")

            trend_points = business_trend_points(entry)
            st.plotly_chart(build_trend_chart(trend_points, "Enterprise count"), key="business_trend")

            insight_key = f"sector:{sector['code']}:{selected_muni}"
            insight_text = insights.get(insight_key, "")
            st.markdown("**Research brief**")
            st.write(insight_text if insight_text else "_No research brief yet for this municipality/sector._")
