"""Kosovo Property & Investment Screener — Streamlit app.

Run with: streamlit run app.py   (from inside the app/ directory)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_advisor
from data_loader import load_data
from scoring import (
    business_trend_points,
    compute_property_ranking,
    housing_trend_points,
    rank_business,
    rank_colors,
)

st.set_page_config(page_title="Kosovo Investment Screener", layout="wide")


def _supports_row_select() -> bool:
    """st.dataframe(on_select=...) row selection needs Streamlit >= 1.35."""
    try:
        major, minor = (int(p) for p in st.__version__.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (1, 35)


SUPPORTS_ROW_SELECT = _supports_row_select()


def build_rank_chart(names: list[str], values: list[float], axis_title: str, suffix: str = "") -> go.Figure:
    """Horizontal bar chart, one color ramp keyed to rank: lightest = lowest,
    darkest = highest. This is one measure ranked, not distinct categories,
    so every bar uses shades of the same blue rather than one color each."""
    pairs = sorted(zip(names, values), key=lambda p: p[1])  # ascending -> bottom to top
    colors = rank_colors(len(pairs))
    fig = go.Figure(
        go.Bar(
            x=[v for _, v in pairs],
            y=[n for n, _ in pairs],
            orientation="h",
            marker_color=colors,
            text=[f"{v:.1f}{suffix}" for _, v in pairs],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig.update_layout(
        xaxis_title=axis_title,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=max(320, 34 * len(pairs)),
    )
    return fig


def build_trend_chart(points: list[tuple[str, float]], y_title: str) -> go.Figure:
    labels = [p[0] for p in points]
    values = [p[1] for p in points]
    fig = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            line=dict(color="#2a78d6", width=3),
            marker=dict(size=9),
        )
    )
    fig.update_layout(
        yaxis_title=y_title,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
    )
    return fig


def select_row(df: pd.DataFrame, name_col: str, key: str) -> str:
    """Row-select on the ranked table if this Streamlit version supports it,
    else fall back to a plain selectbox of names."""
    if SUPPORTS_ROW_SELECT:
        event = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key=key)
        rows = event["selection"]["rows"] if event else []
        row = rows[0] if rows else 0
        return df.iloc[row][name_col]
    st.dataframe(df, hide_index=True)
    return st.selectbox("Pick a row to inspect", df[name_col].tolist(), key=f"{key}_select")


data = load_data()
regions = data["regions"]
housing = data["housing"]
business_sectors = data["business_sectors"]
insights = data.get("insights", {})
national = data.get("national", {})

st.title("Kosovo Property & Investment Screener")
st.info(
    "**Not investment advice.** This ranks regions using public statistics as a "
    "starting point for research, not a recommendation."
)
if national:
    st.caption(
        f"National context: GDP growth {national.get('gdp_growth_pct', '—')}%, "
        f"FDI {national.get('fdi_pct_gdp', '—')}% of GDP "
        f"(as of {national.get('last_updated', '—')})."
    )

ai_advisor.render(data)

tab_property, tab_business = st.tabs(["Buy property", "Invest in a business"])

with tab_property:
    st.subheader("Which region is worth researching for a property purchase?")

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

    if not ranking:
        st.warning("No regions to rank with the current filters.")
    else:
        st.plotly_chart(
            build_rank_chart([r["name"] for r in ranking], [r["personalizedScore"] for r in ranking], "Personalized score"),
            key="property_chart",
        )

        table_df = pd.DataFrame(ranking)[
            ["name", "personalizedScore", "momentumScore", "investment_yoy_pct", "tourism_gap_score", "distance_km"]
        ].round(2)
        table_df.columns = ["Region", "Personalized score", "Momentum score", "Investment YoY %", "Tourism gap (0-1)", "Distance (km)"]

        selected_name = select_row(table_df, "Region", key="property_table")
        detail = next(r for r in ranking if r["name"] == selected_name)
        region_obj = next(r for r in regions if r["name"] == selected_name)

        st.markdown(f"### {selected_name}")
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

        trend_points = housing_trend_points(region_obj["housing_bucket"], housing)
        st.plotly_chart(build_trend_chart(trend_points, "Housing price index (2018 = 100)"), key="property_trend")

        insight_text = insights.get(selected_name, "")
        with st.container(border=True):
            st.markdown("**Research brief**")
            st.write(insight_text if insight_text else "_No research brief yet for this region._")

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
        st.plotly_chart(
            build_rank_chart([r["name"] for r in biz_ranking], [r["growth_pct"] for r in biz_ranking], "Growth %", suffix="%"),
            key="business_chart",
        )

        table_df = pd.DataFrame(biz_ranking)[["name", "growth_pct", "count_latest"]].round(2)
        table_df.columns = ["Municipality", "Growth %", "Enterprises (latest)"]

        selected_muni = select_row(table_df, "Municipality", key="business_table")
        entry = sector["by_municipality"][selected_muni]

        st.markdown(f"### {selected_muni} — {sector['name']}")
        mcol1, mcol2 = st.columns(2)
        mcol1.metric("Growth %", f"{entry['growth_pct']:.1f}%", delta=f"{entry['growth_pct']:.1f}%")
        mcol2.metric("Enterprises (latest)", f"{entry['count_latest']:.0f}")

        trend_points = business_trend_points(entry)
        st.plotly_chart(build_trend_chart(trend_points, "Enterprise count"), key="business_trend")

        insight_key = f"sector:{sector['code']}:{selected_muni}"
        insight_text = insights.get(insight_key, "")
        with st.container(border=True):
            st.markdown("**Research brief**")
            st.write(insight_text if insight_text else "_No research brief yet for this municipality/sector._")
