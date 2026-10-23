"""COP17 2026 Armenia — Executive Sales Console.

Run locally:   streamlit run app.py
Streamlit Cloud: main file = app.py, Python 3.11+, secrets → SOURCE_URL (optional).
"""
from __future__ import annotations

import streamlit as st

from dashboard import config, data, ui

st.set_page_config(
    page_title="COP17 Sales Console",
    page_icon="🦋",
    layout="wide",
    initial_sidebar_state="collapsed",
)
ui.inject_css()


def _secret(name: str, default: str) -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # noqa: BLE001 — no secrets.toml locally
        return default


SOURCE_URL = _secret("SOURCE_URL", config.DEFAULT_SOURCE_URL)
LOCAL_PATH = _secret("LOCAL_PATH", config.LOCAL_FALLBACK)

# ?refresh=1 (used by the RPA after an export) or the Refresh button clears the 5-minute cache.
if st.query_params.get("refresh"):
    data.load_dataset.clear()
    st.query_params.clear()

with st.spinner("Loading sales workbook…"):
    ds = data.load_dataset(SOURCE_URL, LOCAL_PATH)


def go_to_section(section_key: str | None) -> None:
    """Card click on General: switch the tab (None = stay) and scroll to the top on the rerun."""
    if section_key is not None:
        st.session_state["section"] = config.SECTION_BY_KEY[section_key].label
    st.session_state["scroll_top"] = True


# ------------------------------------------------------------------ header row
head, action = st.columns([6, 1.2], vertical_alignment="center")
with head:
    ui.render_header(ds)
with action:
    if st.button("↻ Refresh data", key="refresh", width="stretch"):
        data.load_dataset.clear()
        st.rerun()

if ds.error:
    st.warning(ds.error, icon="⚠️")
if ds.is_empty:
    st.error(
        "No sales data could be loaded. Check the Dropbox link in `.streamlit/secrets.toml` "
        "(`SOURCE_URL`) or place a copy at `data/COP-17-Sales.xlsx`.",
        icon="📄",
    )
    st.stop()

# ------------------------------------------------------------------ navigation + period
section_key = ui.render_tabs()
if st.session_state.pop("scroll_top", False):             # set by a tab click or a section-card click
    ui.scroll_to_top()
section = config.SECTION_BY_KEY[section_key]
info = ds.info.get(section_key)
start, end = ui.render_date_controls(ds)

# ------------------------------------------------------------------ data for this tab
df = data.select(ds, section_key, start, end)                 # daily rows (iiko pivot sheets)
periods = data.select_periods(ds, section_key, start, end)   # period totals fully inside the range
excluded = data.excluded_periods(ds, section_key, start, end)
k = data.kpis(df, periods)
ui.render_section_head(section, info, ds)

if df.empty and not periods:
    ui.render_excluded_note(excluded)
    ui.render_empty(section, start, end, ds)
    st.stop()

ui.render_kpis(k, section, start, end, periods)
ui.render_excluded_note(excluded)
show_discount = k["has_discount"]  # "Сумма скидки" is omitted everywhere when it is 0

if section.kind == "global":
    sections = data.section_totals(df, periods)
    ui.render_charts(sections, data.daily_by_section(df))
    ui.render_section_cards(sections, k, go_to_section)          # click → opens that tab, scrolls to top
elif section.kind == "compliments":
    ui.render_section_table(data.section_totals(df), show_discount, title="Compliments by section")

if section.kind == "sheet":                                  # a period-summary sheet: its summary card
    for p in periods:
        ui.render_period_card(p, ds.info.get(p.section))

if not df.empty:
    ui.render_overall_totals(data.payment_totals(df), show_discount,
                             subtitle="by payment type · daily sheets only" if periods else "by payment type")
    pay_cols = [] if section.kind == "compliments" else data.payment_columns(df)   # compliments have one "payment"
    ui.render_daily_table(data.daily_pivot(df), pay_cols, show_discount, k, periods)
    ui.render_raw(data.raw_records(df), section_key, start, end)
