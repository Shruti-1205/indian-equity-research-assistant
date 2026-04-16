"""Streamlit dashboard for the research system.

Five tabs cover three audiences in one place.
  Home            overview and live KPIs for quick stakeholder briefings
  Deep Dive       run the pipeline for any stock on any date
  Market Pulse    biggest movers, sector heatmap, institutional flow chart
  Macro           global indicator trends
  Benchmark       accuracy metrics from the labeled evaluation run

Run:
  streamlit run src/dashboard/app.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import WATCHLIST, STOCK_TO_SECTOR
from src.agents.graph import run as run_pipeline
from src.data.db import get_conn

st.set_page_config(
    page_title="Indian Equity Research Assistant",
    page_icon="IR",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────
# Styling: clean, professional, minimal.
# ──────────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    .kpi-label { font-size: 0.75rem; color: #6b7280; text-transform: uppercase;
                 letter-spacing: 0.08em; margin-bottom: 4px; }
    .kpi-value { font-size: 1.65rem; font-weight: 600; color: #111827; }
    .kpi-delta-pos { color: #059669; font-size: 0.85rem; font-weight: 500; }
    .kpi-delta-neg { color: #dc2626; font-size: 0.85rem; font-weight: 500; }
    .section-title { font-size: 1.05rem; font-weight: 600; color: #111827;
                     margin-top: 8px; margin-bottom: 12px; }
    .sub-label { color: #6b7280; font-size: 0.8rem; }
    .divider-line { border-top: 1px solid #e5e7eb; margin: 14px 0; }
    div[data-testid="stMetric"] { background-color: #f9fafb; padding: 12px 16px;
                                   border-radius: 6px; border: 1px solid #e5e7eb; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────────────
# Data access helpers
# ──────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def latest_trading_date() -> str:
    con = get_conn()
    d = con.execute("SELECT MAX(date) FROM features").fetchone()[0]
    con.close()
    return str(d) if d else dt.date.today().isoformat()


@st.cache_data(ttl=300)
def price_history(symbol: str, days: int = 180) -> pd.DataFrame:
    con = get_conn()
    df = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE symbol = ? ORDER BY date DESC LIMIT ?", [symbol, days]
    ).df()
    con.close()
    return df.sort_values("date") if not df.empty else df


@st.cache_data(ttl=300)
def biggest_movers(date: str, n: int = 20) -> pd.DataFrame:
    con = get_conn()
    df = con.execute(
        """
        SELECT f.symbol,
               ROUND(f.pct_change_1d, 2)      AS pct_1d,
               ROUND(f.pct_from_52w_high, 1)  AS from_52w_high,
               ROUND(f.vol_vs_20d_avg, 2)     AS vol_multiple,
               p.close
        FROM features f JOIN prices p USING (symbol, date)
        WHERE f.date = CAST(? AS DATE) AND f.symbol NOT LIKE '^%'
        ORDER BY ABS(f.pct_change_1d) DESC LIMIT ?
        """, [date, n]
    ).df()
    con.close()
    return df


@st.cache_data(ttl=300)
def sector_performance(date: str) -> pd.DataFrame:
    """Average 1-day return grouped by sector for the given date."""
    con = get_conn()
    df = con.execute(
        """
        SELECT symbol, pct_change_1d FROM features
        WHERE date = CAST(? AS DATE) AND symbol NOT LIKE '^%'
        """, [date]
    ).df()
    con.close()
    if df.empty:
        return pd.DataFrame(columns=["sector", "avg_return", "stocks"])
    df["sector"] = df["symbol"].map(STOCK_TO_SECTOR).fillna("Other")
    g = df.groupby("sector")["pct_change_1d"].agg(["mean", "count"]).reset_index()
    g.columns = ["sector", "avg_return", "stocks"]
    g["avg_return"] = g["avg_return"].round(2)
    return g.sort_values("avg_return")


@st.cache_data(ttl=600)
def macro_history(days: int = 180) -> pd.DataFrame:
    con = get_conn()
    d = int(days)
    df = con.execute(
        f"SELECT date, series, value FROM macro "
        f"WHERE date >= CURRENT_DATE - INTERVAL '{d}' DAY ORDER BY date"
    ).df()
    con.close()
    return df


@st.cache_data(ttl=600)
def flow_history(days: int = 60) -> pd.DataFrame:
    con = get_conn()
    d = int(days)
    df = con.execute(
        f"SELECT date, fii_net, dii_net FROM fii_dii "
        f"WHERE date >= CURRENT_DATE - INTERVAL '{d}' DAY ORDER BY date"
    ).df()
    con.close()
    return df


@st.cache_data(ttl=60)
def db_health() -> dict:
    con = get_conn()
    out = {}
    for tbl in ("prices", "features", "fii_dii", "macro", "pdf_cache"):
        out[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    out["stocks"] = con.execute(
        "SELECT COUNT(DISTINCT symbol) FROM prices WHERE symbol NOT LIKE '^%'"
    ).fetchone()[0]
    from src.rag.chroma_store import stats as chroma_stats
    out["announcements"] = chroma_stats().get("count", 0)
    con.close()
    return out


@st.cache_data(ttl=600)
def load_benchmark_report() -> dict | None:
    path = ROOT / "benchmark" / "report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# HOME tab: welcome, navigation guide, and live system status
# ──────────────────────────────────────────────────────────────────────────

def kpi(label: str, value: str):
    st.markdown(
        f"<div class='kpi-label'>{label}</div>"
        f"<div class='kpi-value'>{value}</div>",
        unsafe_allow_html=True,
    )


def _render_nl_query(text: str):
    """Handle a natural language query from the Home page query box.

    Uses the orchestrator to classify intent, then routes to the right
    handler and renders a clean, inline response.
    """
    from src.agents.orchestrator import orchestrate
    from src.agents.handlers import (
        market_overview, stock_screen, search_filings,
    )

    with st.spinner("Thinking..."):
        plan = orchestrate(text)

    intent = plan.get("intent")
    st.caption(f"Interpreted as: **{intent}**"
               + (f" for `{plan['symbol']}`" if plan.get("symbol") else "")
               + f" on `{plan.get('query_date', 'today')}`")

    if intent == "explain_move" and plan.get("symbol"):
        with st.spinner("Running price, event, flow, macro agents..."):
            state = run_pipeline(plan["symbol"], plan["query_date"], plan.get("user_hint", ""))
        # Use the effective date that the price agent actually resolved to
        # (latest trading day on or before the requested date). Avoids showing
        # a future date header when the body correctly cites the last session.
        effective = (state.get("price") or {}).get("date") or plan["query_date"]
        st.markdown(f"### {plan['symbol']} on {effective}")
        if str(effective) != str(plan["query_date"]):
            st.caption(f"(Requested {plan['query_date']}. Most recent trading "
                       f"session with data is {effective}.)")
        st.write(state.get("explanation") or "No explanation generated.")
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("Likely driver", state.get("primary_driver", "?").title())
        with c2: st.metric("Confidence", state.get("confidence", "?").title())
        with c3:
            ok = state.get("validation_ok")
            st.metric("Grounding", "OK" if ok else "Flagged")

    elif intent == "market_overview":
        with st.spinner("Assembling market overview..."):
            r = market_overview(plan["query_date"], plan.get("user_hint", ""))
        if r.get("error"):
            st.error(r["error"]); return
        st.markdown(f"### Market on {r.get('date')}")
        st.write(r.get("summary", ""))
        mc1, mc2 = st.columns(2)
        with mc1:
            st.markdown("**Top gainers**")
            for row in r.get("top_gainers", []):
                sym = row["symbol"].replace(".NS", "")
                st.caption(f"{sym}: +{row['pct_1d']}% (vol {row['vol_mult']}x)")
        with mc2:
            st.markdown("**Top losers**")
            for row in r.get("top_losers", []):
                sym = row["symbol"].replace(".NS", "")
                st.caption(f"{sym}: {row['pct_1d']}% (vol {row['vol_mult']}x)")

    elif intent == "stock_screen":
        with st.spinner("Running screener..."):
            r = stock_screen(plan["query_date"], plan.get("user_hint", ""))
        st.markdown(f"### {r.get('filter_label', 'Screen')}")
        if r.get("summary"):
            st.write(r["summary"])
        rows = r.get("rows", [])
        if rows:
            df = pd.DataFrame(rows)
            df["symbol"] = df["symbol"].str.replace(".NS", "", regex=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No matches.")

    elif intent == "search_filings":
        with st.spinner("Searching corporate filings..."):
            r = search_filings(plan.get("user_hint", ""), symbol=plan.get("symbol"))
        st.markdown(f"### Filings matching: {r.get('topic')}")
        st.write(r.get("summary", ""))
        for h in r.get("hits", []):
            with st.expander(f"{h.get('date')}: {h.get('symbol')} "
                             f"[{h.get('category','?')[:24]}]"):
                st.write(h.get("text", ""))

    else:
        st.info(
            "I could not understand that question. Try something like 'Why did "
            "Reliance drop today?' or 'Any bonus share announcements this month?'"
        )


def render_home():
    # Welcome block
    st.markdown(
        "<div style='font-size:1.3rem;font-weight:600;color:#111827;"
        "margin-bottom:4px;'>Welcome</div>",
        unsafe_allow_html=True,
    )
    st.write(
        "This is a research tool for Indian equities. It answers questions like "
        "why a stock moved on a given day, how the market or a sector performed, "
        "which stocks are near their 52 week highs, and what corporate filings "
        "have been released on a specific topic. Every answer is traced to its "
        "primary source. Figures that cannot be verified in the source data are "
        "flagged and not shown."
    )

    # Natural language query box. Routes through the orchestrator.
    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='section-title'>Ask a question</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Type any question in plain English. Examples: 'Why did Reliance drop today?' "
        "'How did the market do today?' 'Which stocks hit 52 week highs?' "
        "'Any bonus share announcements this month?'"
    )
    q_col, q_btn = st.columns([5, 1])
    with q_col:
        user_q = st.text_input(
            "query", placeholder="Ask anything about Indian stocks...",
            label_visibility="collapsed", key="home_query",
        )
    with q_btn:
        run_q = st.button("Ask", type="primary", use_container_width=True,
                          key="home_ask_btn")

    if run_q and user_q.strip():
        _render_nl_query(user_q.strip())

    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)

    # Navigation guide
    st.markdown(
        "<div class='section-title'>How to use this app</div>",
        unsafe_allow_html=True,
    )
    nav1, nav2, nav3, nav4 = st.columns(4)
    with nav1:
        st.markdown("**Deep Dive**")
        st.caption(
            "Pick a stock and a date. The system runs four specialist agents "
            "and produces a cited explanation of why that stock moved."
        )
    with nav2:
        st.markdown("**Market Pulse**")
        st.caption(
            "A live briefing of today's biggest movers, sector leaderboard, "
            "and institutional flow over the last 60 days."
        )
    with nav3:
        st.markdown("**Macro**")
        st.caption(
            "Global indicators that matter for Indian stocks. Crude oil, US VIX, "
            "US Treasury yields, and the rupee exchange rate."
        )
    with nav4:
        st.markdown("**Benchmark**")
        st.caption(
            "Measured accuracy from a held out evaluation set. Shows how the "
            "system performs across different types of price moves."
        )

    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)

    # Live system snapshot
    st.markdown(
        "<div class='section-title'>Current data coverage</div>",
        unsafe_allow_html=True,
    )
    health = db_health()
    date = latest_trading_date()
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi("Stocks tracked", f"{health.get('stocks', 0)}")
    with c2: kpi("Price rows", f"{health.get('prices', 0):,}")
    with c3: kpi("BSE announcements", f"{health.get('announcements', 0):,}")
    with c4: kpi("PDFs parsed", f"{health.get('pdf_cache', 0):,}")
    with c5: kpi("Latest date", date)

    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)

    # A quick glance of today's market
    st.markdown(
        "<div class='section-title'>At a glance</div>",
        unsafe_allow_html=True,
    )
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.caption("Biggest movers on the most recent trading day")
        df = biggest_movers(date, n=10)
        if df.empty:
            st.info("No data yet. Run the bootstrap script first.")
        else:
            fig = go.Figure()
            colors = ["#16a34a" if v >= 0 else "#dc2626" for v in df["pct_1d"]]
            fig.add_trace(go.Bar(
                x=df["pct_1d"],
                y=[s.replace(".NS", "") for s in df["symbol"]],
                orientation="h",
                marker_color=colors,
                text=[f"{v:+.2f}%" for v in df["pct_1d"]],
                textposition="outside",
            ))
            fig.update_layout(
                height=360,
                margin=dict(l=10, r=30, t=10, b=10),
                xaxis_title="One day return (%)",
                yaxis=dict(autorange="reversed"),
                showlegend=False,
                plot_bgcolor="white",
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.caption("Sector averages on the most recent trading day")
        sec = sector_performance(date)
        if sec.empty:
            st.info("Sector data unavailable.")
        else:
            fig = go.Figure(go.Bar(
                x=sec["avg_return"],
                y=sec["sector"],
                orientation="h",
                marker_color=["#dc2626" if v < 0 else "#16a34a" for v in sec["avg_return"]],
                text=[f"{v:+.2f}%" for v in sec["avg_return"]],
                textposition="outside",
            ))
            fig.update_layout(
                height=360, margin=dict(l=10, r=30, t=10, b=10),
                xaxis_title="Avg return (%)",
                showlegend=False,
                plot_bgcolor="white",
            )
            st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────
# DEEP DIVE tab
# ──────────────────────────────────────────────────────────────────────────

def confidence_color(conf: str) -> str:
    return {"high": "#059669", "medium": "#d97706", "low": "#dc2626"}.get(conf, "#6b7280")


def driver_description(driver: str) -> str:
    return {
        "company": "Company specific news moved this stock more than its sector",
        "sector":  "The move matches broader sector behaviour",
        "macro":   "Global macro conditions drove a risk-off or risk-on day",
        "flow":    "Large institutional flow explains the move",
        "unclear": "No single driver stood out in the available evidence",
    }.get(driver, driver)


def render_deep_dive():
    st.subheader("Stock deep dive")
    st.caption("Ask the system to explain any single-day move with cited sources.")

    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        symbol = st.selectbox("Stock", WATCHLIST,
                              index=WATCHLIST.index("EICHERMOT.NS") if "EICHERMOT.NS" in WATCHLIST else 0)
    with c2:
        default = dt.date.fromisoformat(latest_trading_date())
        query_date = st.date_input("Trading date", value=default, max_value=default)
    with c3:
        st.write("")
        st.write("")
        run_btn = st.button("Analyse", type="primary", use_container_width=True)

    # Always show price context
    ph = price_history(symbol, days=180)
    if not ph.empty:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=ph["date"], open=ph["open"], high=ph["high"],
            low=ph["low"], close=ph["close"], name=symbol,
            showlegend=False,
        ))
        fig.add_shape(
            type="line",
            x0=str(query_date), x1=str(query_date),
            y0=0, y1=1, yref="paper",
            line=dict(color="#6b7280", width=1, dash="dash"),
        )
        fig.update_layout(
            height=360, margin=dict(l=10, r=10, t=30, b=10),
            xaxis_rangeslider_visible=False,
            title=f"{symbol.replace('.NS','')} price (last 180 days)",
        )
        st.plotly_chart(fig, use_container_width=True)

    if not run_btn:
        st.info("Pick a stock and date above, then click Analyse to run the four specialist agents in parallel.")
        return

    with st.spinner("Running price, event, flow, and macro agents. Synthesising an answer."):
        state = run_pipeline(symbol, str(query_date), "")

    # Headline card
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"### What drove {symbol.replace('.NS','')} on {query_date}")
        st.write(state.get("explanation", "No explanation generated."))
        citations = state.get("citations") or []
        if citations:
            st.caption(f"Sources cited: {', '.join(citations)}")

    with right:
        driver = state.get("primary_driver", "unclear")
        conf = state.get("confidence", "low")
        st.markdown(
            f"<div style='background:#f9fafb;border:1px solid #e5e7eb;"
            f"border-radius:8px;padding:14px;'>"
            f"<div class='kpi-label'>Likely driver</div>"
            f"<div style='font-size:1.2rem;font-weight:600;color:#111827;margin:2px 0 6px 0;'>"
            f"{driver.title()}</div>"
            f"<div class='sub-label'>{driver_description(driver)}</div>"
            f"<div style='margin-top:12px;'>"
            f"<span class='kpi-label'>Confidence</span><br>"
            f"<span style='color:{confidence_color(conf)};font-weight:600;font-size:1.1rem;'>"
            f"{conf.title()}</span></div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if state.get("validation_ok") is True:
            st.success("All figures grounded in source data")
        elif state.get("validation_ok") is False:
            st.warning(f"Unverified: {state.get('unverified_claims')}")
        if state.get("changes_made"):
            removed = state.get("hallucinations_removed", [])
            with st.expander(f"Verifier corrected {len(removed)} claim(s)"):
                for h in removed:
                    st.code(str(h), language="text")

    # Evidence section
    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)
    st.markdown("#### Evidence used by the agents")
    ev1, ev2, ev3, ev4 = st.columns(4)

    price = state.get("price") or {}
    with ev1:
        st.markdown("**Price action**")
        if price:
            st.metric("One day return",
                      f"{price.get('pct_change_1d'):+.2f}%" if price.get("pct_change_1d") is not None else "n/a")
            st.caption(f"Sector: {price.get('sector_return_pct','?')}%")
            st.caption(f"Nifty: {price.get('nifty_return_pct','?')}%")
            if price.get("vol_vs_20d_avg") is not None:
                st.caption(f"Volume: {price.get('vol_vs_20d_avg'):.2f}x 20 day avg")
            if price.get("pct_from_52w_high") is not None:
                st.caption(f"Off 52w high: {price.get('pct_from_52w_high'):+.1f}%")

    events = (state.get("events") or {}).get("events", [])
    with ev2:
        st.markdown("**BSE filings**")
        mat = [e for e in events if e.get("material")]
        st.caption(f"{len(events)} in last 14 days, {len(mat)} flagged material.")
        for e in events[:4]:
            mark = "●" if e.get("material") else "○"
            st.caption(f"{mark} {e.get('date')}: {e.get('text','')[:80]}")

    flow = state.get("flow") or {}
    with ev3:
        st.markdown("**Institutional flow**")
        if flow.get("fii_net_cr") is not None:
            st.metric("FII net",
                      f"Rs {flow.get('fii_net_cr'):+,.0f} cr")
            st.caption(f"DII net: Rs {flow.get('dii_net_cr'):+,.0f} cr")
            if flow.get("days_available"):
                st.caption(f"History available: {flow['days_available']} day(s)")
        else:
            st.caption("No flow data for this date.")

    macro = state.get("macro") or {}
    with ev4:
        st.markdown("**Global macro**")
        if macro.get("vix") is not None:
            st.metric("VIX", f"{macro.get('vix'):.2f}",
                      help=f"20 day avg {macro.get('vix_20d_avg')}")
            st.caption(f"Crude: {macro.get('crude_wti','?')} "
                       f"({macro.get('crude_1d_chg_pct','?')}% day)")
            st.caption(f"US 10Y: {macro.get('us_10y','?')}%")
            st.caption(f"Risk off: {'yes' if macro.get('risk_off') else 'no'}")

    # Material PDFs
    material = [e for e in events if e.get("material")]
    if material:
        st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)
        st.markdown("#### Source filings referenced")
        from src.agents.synthesis_agent import _strip_boilerplate
        for e in material[:4]:
            with st.expander(f"{e.get('date')}: {e.get('text','')[:90]}"):
                st.caption(f"Category: {e.get('category')} | "
                           f"PDF status: {e.get('pdf_status','?')} | "
                           f"Pages: {e.get('page_count',0)}")
                full = e.get("full_text") or ""
                # Strip repetitive corporate-letter boilerplate so the excerpt
                # shows the substantive content, not addresses and CIN numbers.
                cleaned = _strip_boilerplate(full) if full else ""
                st.text(cleaned[:4000] if cleaned else "(PDF not available)")


# ──────────────────────────────────────────────────────────────────────────
# MARKET PULSE tab
# ──────────────────────────────────────────────────────────────────────────

def render_market_pulse():
    st.subheader("Market pulse")
    date = latest_trading_date()
    st.caption(f"Snapshot for {date}")

    left, right = st.columns([2, 1])

    with left:
        st.markdown("**Top 20 movers**")
        df = biggest_movers(date, n=20)
        if df.empty:
            st.info("No data.")
        else:
            df_display = df.copy()
            df_display["symbol"] = df_display["symbol"].str.replace(".NS", "", regex=False)
            df_display.columns = ["Stock", "1D %", "From 52w high %",
                                  "Volume mult", "Close"]
            st.dataframe(df_display, use_container_width=True, hide_index=True)

    with right:
        st.markdown("**Sector leaderboard**")
        sec = sector_performance(date)
        if not sec.empty:
            fig = px.bar(sec.sort_values("avg_return"),
                         x="avg_return", y="sector", orientation="h",
                         color="avg_return",
                         color_continuous_scale=["#dc2626", "#f9fafb", "#059669"],
                         color_continuous_midpoint=0,
                         labels={"avg_return": "Average return (%)",
                                 "sector": ""})
            fig.update_layout(height=500, showlegend=False,
                              coloraxis_showscale=False,
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # Institutional flow chart
    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)
    st.markdown("**Institutional activity (last 60 days)**")
    fl = flow_history(days=60)
    if fl.empty:
        st.info("Flow data builds up with daily refresh_macro runs.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=fl["date"], y=fl["fii_net"],
                             name="FII net", marker_color="#3b82f6"))
        fig.add_trace(go.Bar(x=fl["date"], y=fl["dii_net"],
                             name="DII net", marker_color="#f59e0b"))
        fig.update_layout(
            height=320, barmode="group",
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="Net flow (Rs crore)",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────
# MACRO tab
# ──────────────────────────────────────────────────────────────────────────

def render_macro():
    st.subheader("Global macro context")
    st.caption("FRED indicators relevant to Indian equities. Crude and rupee "
               "matter most for oil importers and IT exporters. VIX flags risk appetite.")

    df = macro_history(days=365)
    if df.empty:
        st.info("No macro data yet. Run `python -m scripts.refresh_macro`.")
        return

    pivot = df.pivot(index="date", columns="series", values="value")
    pairs = [
        ("CRUDE_WTI", "WTI Crude, USD per barrel"),
        ("US_VIX", "US VIX (fear index)"),
        ("US_10Y", "US 10 Year Treasury yield, %"),
        ("USD_INR", "USD to INR"),
        ("DXY_BROAD", "Broad dollar index"),
    ]

    cols = st.columns(2)
    for i, (series, title) in enumerate(pairs):
        if series not in pivot.columns:
            continue
        with cols[i % 2]:
            series_df = pivot[series].dropna().reset_index()
            series_df.columns = ["date", "value"]
            fig = px.line(series_df, x="date", y="value", title=title)
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=40, b=10),
                              yaxis_title="", xaxis_title="")
            st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────────────────
# BENCHMARK tab
# ──────────────────────────────────────────────────────────────────────────

def render_benchmark():
    st.subheader("Model evaluation")
    st.caption(
        "Results from the labeled benchmark. The system is evaluated "
        "against ground-truth labels produced by an independent judge model "
        "reading the same evidence the pipeline sees."
    )

    report = load_benchmark_report()
    if report is None:
        st.warning("No benchmark report available yet.")
        return

    # Primary metric: numeric grounding
    hero1, hero2 = st.columns([2, 1])
    with hero1:
        val = report.get("validation_ok_rate", 0) * 100
        st.markdown(
            f"<div class='kpi-label'>Numeric grounding pass rate</div>"
            f"<div style='font-size:2.8rem;font-weight:700;color:#111827;"
            f"line-height:1;margin:4px 0 6px 0;'>{val:.1f}%</div>"
            f"<div class='sub-label'>Explanations where every cited figure "
            f"appears verbatim in the source data. The system redacts any "
            f"number it cannot verify.</div>",
            unsafe_allow_html=True,
        )
    with hero2:
        hal = report.get("hallucination_rate", 0) * 100
        st.markdown(
            f"<div class='kpi-label'>Hallucination rate</div>"
            f"<div class='kpi-value' style='color:#111827;'>{hal:.1f}%</div>"
            f"<div class='sub-label'>Unverified numbers are automatically "
            f"redacted before reaching the reader.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)

    # Secondary: classification metrics
    st.markdown(
        "<div class='section-title'>Driver classification</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "A secondary output of the system is a three-way label (company, "
        "sector, unclear) describing what drove the move. This is an "
        "inherently judgmental task."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Cases evaluated", report.get("n_cases", 0))
    with c2:
        acc = report.get("driver_accuracy", 0) * 100
        st.metric("Overall accuracy", f"{acc:.1f}%")
    with c3:
        st.metric("Errors during run", report.get("n_errors", 0))

    # Optional per-class breakdown (only if confusion matrix is available)
    rows_data = report.get("results", []) or []
    if rows_data:
        per_class = {}
        df_res = pd.DataFrame(rows_data)
        for driver in ("company", "sector", "unclear"):
            subset = df_res[df_res["expected"] == driver]
            if len(subset) > 0:
                correct = int((subset["predicted"] == driver).sum())
                per_class[driver] = {
                    "total": len(subset),
                    "correct": correct,
                    "accuracy": correct / len(subset) * 100,
                }
        if per_class:
            st.markdown(
                "<div class='sub-label' style='margin-top:10px;'>"
                "Per class accuracy:</div>",
                unsafe_allow_html=True,
            )
            cols = st.columns(len(per_class))
            for col, (driver, stats) in zip(cols, per_class.items()):
                with col:
                    st.metric(
                        f"{driver.title()}",
                        f"{stats['accuracy']:.0f}%",
                        f"{stats['correct']} of {stats['total']} correct",
                    )

    st.markdown("<div class='divider-line'></div>", unsafe_allow_html=True)

    # Distribution charts (compact)
    dc1, dc2 = st.columns(2)
    with dc1:
        st.markdown("<div class='sub-label'>Confidence distribution</div>",
                    unsafe_allow_html=True)
        conf = report.get("confidence_distribution", {}) or {}
        if conf:
            fig = px.pie(
                values=list(conf.values()),
                names=[k.title() for k in conf.keys()],
                color_discrete_sequence=["#16a34a", "#d97706", "#dc2626"],
            )
            fig.update_layout(height=240, margin=dict(l=10, r=10, t=5, b=5),
                              showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
    with dc2:
        st.markdown("<div class='sub-label'>Driver distribution</div>",
                    unsafe_allow_html=True)
        drv = report.get("driver_distribution", {}) or {}
        if drv:
            fig = px.bar(
                x=list(drv.values()),
                y=[k.title() for k in drv.keys()],
                orientation="h",
                color_discrete_sequence=["#3b82f6"],
                labels={"x": "Cases", "y": ""},
            )
            fig.update_layout(height=240, margin=dict(l=10, r=10, t=5, b=5),
                              showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    # Per-case table: collapsed by default.
    if rows_data:
        with st.expander("Show per case results (all 100+ cases)"):
            df = pd.DataFrame(rows_data)
            show_cols = [c for c in ["symbol", "date", "expected", "predicted",
                                     "match", "confidence", "validation_ok",
                                     "latency_s"] if c in df.columns]
            st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


# ──────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────

st.title("Indian Equity Research Assistant")
st.markdown(
    "<div class='sub-label'>Explains why stocks move, using only verified "
    "data from exchange filings, price feeds, and government sources.</div>",
    unsafe_allow_html=True,
)
st.write("")

tab_home, tab_deep, tab_pulse, tab_macro, tab_bench = st.tabs(
    ["Home", "Deep Dive", "Market Pulse", "Macro", "Benchmark"]
)

with tab_home:     render_home()
with tab_deep:     render_deep_dive()
with tab_pulse:    render_market_pulse()
with tab_macro:    render_macro()
with tab_bench:    render_benchmark()

# Sidebar: compact reference
with st.sidebar:
    st.markdown("### About")
    st.write(
        "A research assistant for Indian equities that produces cited, "
        "grounded answers to stock market questions."
    )
    st.markdown("---")
    st.markdown("**Data sources**")
    st.caption("Yahoo Finance for NSE prices and volumes")
    st.caption("BSE corporate announcements API for filings")
    st.caption("NSE daily summary for FII and DII flow")
    st.caption("FRED (Federal Reserve) for global macro")
    st.markdown("---")
    st.markdown("**How it works**")
    st.caption(
        "Four specialist agents gather evidence in parallel. A large "
        "language model writes the answer. A validator checks that every "
        "number appears in the source data. Unverified figures are redacted."
    )
