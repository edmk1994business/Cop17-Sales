"""COP17 2026 Armenia — Executive Sales Dashboard.

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
if ds.df.empty:
    st.error(
        "No sales data could be loaded. Check the Dropbox link in `.streamlit/secrets.toml` "
        "(`SOURCE_URL`, ending in `dl=1`) or place a copy at `data/COP-17-Sales.xlsx`.",
        icon="📄",
    )
    st.stop()

# ------------------------------------------------------------------ navigation + period
section_key = ui.render_tabs()
section = config.SECTION_BY_KEY[section_key]
start, end = ui.render_date_controls(ds)

# ------------------------------------------------------------------ data for this tab
df = data.select(ds, section_key, start, end)
k = data.kpis(df)
ui.render_section_head(section, ds.info.get(section_key), k)

if df.empty:
    ui.render_empty(section, start, end, ds)
    st.stop()

ui.render_kpis(k, section, start, end)
show_discount = k["has_discount"]  # "Сумма скидки" is omitted everywhere when it is 0

if section.kind == "global":
    sections = data.section_totals(df)
    ui.render_charts(sections, data.daily_by_section(df))
    ui.render_section_table(sections, ds.info, show_discount)
elif section.kind == "compliments":
    ui.render_section_table(data.section_totals(df), ds.info, show_discount)  # where the compliments came from

ui.render_overall_totals(data.payment_totals(df), show_discount)
ui.render_daily_table(data.daily_breakdown(df), show_discount)
ui.render_raw(data.raw_records(df), section_key, start, end)
