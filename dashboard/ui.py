"""Presentation layer: theme CSS, header, tab bar, date controls, KPI cards, tables and charts.

Everything visual is rendered through ``st.html`` so the layout is one coherent system
(100% width, phone-friendly) instead of Streamlit defaults. Rules learnt on Streamlit 1.64:
  * ``st.html`` drops the whole element if a literal tag appears inside a style or script
    block, so the CSS below never contains a "<tag>" string and there is no inline JS.
  * The tab bar / preset pills are ``st.radio`` widgets restyled through
    ``[data-testid=stRadioOption][data-selected=true]``.
"""
from __future__ import annotations

import base64
import html
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from . import config, dates
from .config import THEME as T
from .data import Dataset, PeriodSummary, SectionInfo

ASSETS = Path(__file__).resolve().parent.parent / "assets"


# ----------------------------------------------------------------------------- formatting
def fmt_n(x) -> str:
    """Whole number with thousands separators; no decimals."""
    try:
        return f"{int(round(float(x))):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_money(x) -> str:
    return f"{fmt_n(x)} {config.CURRENCY}"


def fmt_disc(x) -> str:
    """Discount cells: a dash for zero, so the column reads at a glance."""
    return "—" if not x or abs(float(x)) < 0.5 else fmt_n(x)


def fmt_pct(x) -> str:
    v = float(x) * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 0.05 else f"{v:.1f}%"


def fmt_day(d: date) -> str:
    """'Sat 10 Oct 2026'."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b %Y')}"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ----------------------------------------------------------------------------- theme
def inject_css() -> None:
    css = f"""
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    /* ---- clean interface + mobile overflow overrides (requested) ---- */
    html, body, [data-testid="stAppViewContainer"], .main {{
        overflow-x: hidden !important;
        max-width: 100vw !important;
    }}
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    [data-testid="stHeader"] {{display: none !important;}}
    [data-testid="stToolbar"] {{display: none !important;}}
    .viewerBadge_container__1s52n, .stAppViewerFooter {{display: none !important;}}
    div[class*="stAppToolbar"],
    div[data-testid="stDecoration"],
    [data-testid="stStatusWidget"] {{
        display: none !important;
    }}
    [data-testid="stAppToolbar"] {{display: none !important;}}
    .block-container {{
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1.5rem !important;
        padding-bottom: 5rem !important;
        max-width: 100% !important;
    }}
    @media (min-width: 900px) {{
        .block-container {{ padding-left: 2.5rem !important; padding-right: 2.5rem !important; padding-top: 2rem !important; }}
    }}
    [data-testid="stMain"] {{ overflow-x: hidden; }}
    .tbl-wrap, .lg, .kpi-grid, .sec-grid {{ max-width: 100%; }}
    /* the date-picker calendar's month navigation is a header element: bring it back */
    [data-testid="stDateInputCalendar"] header,
    [data-testid="stDateInputCalendar"] header * {{visibility: visible !important;}}

    /* ---- console theme ---- */
    :root {{
        --bg: {T['bg']}; --surface: {T['surface']}; --border: {T['border']};
        --ink: {T['ink']}; --ink-2: {T['ink_2']}; --ink-3: {T['ink_3']};
        --green: {T['green']}; --green-dark: {T['green_dark']}; --green-soft: {T['green_soft']};
        --blue: {T['blue']}; --blue-soft: {T['blue_soft']};
        --gold: {T['gold']}; --gold-soft: {T['gold_soft']}; --coral: {T['coral']};
        --up: {T['up']}; --down: {T['down']};
        --radius: 14px; --shadow: 0 1px 2px rgba(21,35,27,.04), 0 6px 18px -8px rgba(21,35,27,.12);
    }}
    .stApp, [data-testid="stAppViewContainer"] {{ background: var(--bg); }}
    [data-testid="stAppViewContainer"] {{ overflow-x: clip; }}
    .stApp, .stApp p, .stApp div, .stApp span:not([data-testid="stIconMaterial"]), .stApp td, .stApp th {{
        font-family: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    .stApp {{ color: var(--ink); }}
    .stApp a {{ color: var(--blue); }}
    [data-testid="stVerticalBlock"] {{ gap: 0.6rem; }}

    /* ---- header ---- */
    .cop-head {{ display:flex; align-items:center; gap:22px; flex-wrap:wrap; margin: 2px 0 6px; }}
    .cop-logo {{ width:220px; max-width:100%; height:auto; border-radius:14px; border:1px solid var(--border); background:#fff; padding:12px 16px; margin:2px 4px 2px 0; object-fit:contain; box-shadow: var(--shadow); image-rendering: -webkit-optimize-contrast; }}
    .cop-title {{ font-size: clamp(1.35rem, 2.4vw, 1.9rem); font-weight:800; letter-spacing:-0.02em; line-height:1.1; color:var(--ink); }}
    .cop-sub {{ color: var(--ink-2); font-size:.92rem; margin-top:4px; }}
    .cop-status {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }}
    .chip {{ display:inline-flex; align-items:center; gap:6px; font-size:.74rem; font-weight:600; padding:4px 10px; border-radius:999px; border:1px solid var(--border); background:var(--surface); color:var(--ink-2); white-space:nowrap; }}
    .chip-dot {{ width:7px; height:7px; border-radius:50%; background:var(--green); display:inline-block; }}
    .chip-dot.amber {{ background: var(--gold); }}
    .chip-dot.red {{ background: var(--coral); }}
    .chip-dot.grey {{ background: var(--ink-3); }}

    /* ---- pills (st.radio restyled) ---- */
    .st-key-tabs [data-testid="stRadioGroup"], .st-key-presets [data-testid="stRadioGroup"] {{
        display:flex; flex-direction:row; flex-wrap:wrap; gap:6px; padding:2px 2px 6px;
    }}
    .st-key-tabs [data-testid="stRadioGroup"] > div, .st-key-presets [data-testid="stRadioGroup"] > div {{ margin:0; flex:0 0 auto; }}
    .st-key-tabs [data-testid="stRadioGroup"], .st-key-presets [data-testid="stRadioGroup"] {{ position:relative; }}
    .st-key-tabs [data-testid="stRadioOption"], .st-key-presets [data-testid="stRadioOption"] {{
        position:relative;   /* contains the visually-hidden native input, so it cannot widen the page */
        display:flex; align-items:center; margin:0 !important; padding:9px 16px; border-radius:999px; cursor:pointer;
        border:1px solid var(--border); background:var(--surface); color:var(--ink-2); white-space:nowrap;
        box-shadow: var(--shadow); transition: background .15s, border-color .15s, color .15s, transform .15s;
    }}
    .st-key-tabs [data-testid="stRadioOption"]:hover, .st-key-presets [data-testid="stRadioOption"]:hover {{ border-color: var(--green); color: var(--ink); }}
    .st-key-tabs [data-testid="stRadioOption"] > div > div:first-child,
    .st-key-presets [data-testid="stRadioOption"] > div > div:first-child {{ display:none; }}
    .st-key-tabs [data-testid="stRadioOption"] p, .st-key-presets [data-testid="stRadioOption"] p {{ font-size:.9rem; font-weight:600; line-height:1.2; margin:0; color:inherit; }}
    .st-key-tabs [data-testid="stRadioOption"][data-selected="true"] {{ background: var(--green); border-color: var(--green); color:#fff; }}
    .st-key-tabs [data-testid="stRadioOption"][data-selected="true"] p {{ color:#fff; }}
    .st-key-presets [data-testid="stRadioOption"] {{ padding:7px 14px; box-shadow:none; }}
    .st-key-presets [data-testid="stRadioOption"] p {{ font-size:.82rem; }}
    .st-key-presets [data-testid="stRadioOption"][data-selected="true"] {{ background: var(--ink); border-color: var(--ink); color:#fff; }}
    .st-key-presets [data-testid="stRadioOption"][data-selected="true"] p {{ color:#fff; }}
    .st-key-tabs [data-testid="stWidgetLabel"], .st-key-presets [data-testid="stWidgetLabel"] {{ display:none; }}
    .st-key-tabs [data-testid="stElementContainer"], .st-key-tabs [data-testid="stRadio"],
    .st-key-presets [data-testid="stElementContainer"], .st-key-presets [data-testid="stRadio"] {{ width:100% !important; max-width:100%; min-width:0; }}

    /* ---- controls row ---- */
    .st-key-presets {{ min-width: 0; }}
    .range-chip {{ display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border-radius:10px; background:var(--green-soft); color:var(--green-dark); font-weight:600; font-size:.84rem; white-space:nowrap; }}
    .st-key-refresh button, .st-key-show_full button {{ border-radius:10px; border:1px solid var(--border); background:var(--surface); color:var(--ink-2); font-weight:600; box-shadow:var(--shadow); }}
    .st-key-refresh button:hover, .st-key-show_full button:hover {{ border-color: var(--green); color: var(--green-dark); }}
    [data-testid="stDateInput"] label p {{ font-size:.78rem; color:var(--ink-3); font-weight:600; letter-spacing:.02em; text-transform:uppercase; }}

    /* ---- section head ---- */
    .sec-head {{ display:flex; align-items:center; gap:14px; margin:6px 0 2px; flex-wrap:wrap; }}
    .sec-icon {{ width:44px; height:44px; border-radius:12px; display:flex; align-items:center; justify-content:center; font-size:1.35rem; background: color-mix(in srgb, var(--accent) 12%, white); border:1px solid color-mix(in srgb, var(--accent) 28%, white); }}
    .sec-title {{ font-size:1.2rem; font-weight:800; letter-spacing:-0.01em; }}
    .sec-meta {{ font-size:.8rem; color: var(--ink-3); margin-top:2px; }}
    .badge {{ display:inline-flex; align-items:center; gap:6px; font-size:.72rem; font-weight:700; letter-spacing:.03em; text-transform:uppercase; padding:4px 10px; border-radius:8px; }}
    .badge-live {{ background: var(--green-soft); color: var(--green-dark); }}
    .badge-missing {{ background: #FBE9E5; color: #8A2E1E; }}
    .badge-mixed {{ background: var(--blue-soft); color: #244B70; }}
    .badge-period {{ background: var(--blue-soft); color: #2F4350; }}
    .tag-period {{ display:inline-block; font-size:.66rem; font-weight:700; letter-spacing:.03em; text-transform:uppercase; padding:2px 7px; border-radius:6px; background:var(--blue-soft); color:#2F4350; margin-left:8px; vertical-align:middle; white-space:nowrap; }}
    .note {{ font-size:.8rem; color: var(--ink-2); background: var(--gold-soft); border:1px solid #F0E2BE; border-radius:10px; padding:8px 12px; margin-top:6px; }}
    .gt {{ display:flex; align-items:center; gap:10px 14px; flex-wrap:wrap; margin:10px 0 2px; }}
    .gt-item {{ display:flex; flex-direction:column; gap:2px; padding:8px 12px; border-radius:10px; background:#F3F6F2; border:1px solid var(--border); min-width:0; }}
    .gt-grand {{ background: var(--green-soft); border-color: #CFE3D5; }}
    .gt-label {{ font-size:.68rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; color:var(--ink-3); max-width:420px; line-height:1.3; }}
    .gt-value {{ font-size:1.02rem; font-weight:800; color:var(--ink); font-variant-numeric: tabular-nums; white-space:nowrap; }}
    .gt-grand .gt-value {{ color: var(--green-dark); }}
    .gt-plus {{ font-weight:800; color: var(--ink-3); }}

    /* ---- KPI cards ---- */
    .kpi-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:12px; margin: 6px 0 4px; }}
    .kpi {{ position:relative; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px 18px 14px 20px; box-shadow:var(--shadow); overflow:hidden; min-width:0; }}
    .kpi:before {{ content:""; position:absolute; left:0; top:12px; bottom:12px; width:4px; border-radius:0 4px 4px 0; background: var(--accent); }}
    .kpi-label {{ font-size:.74rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color: var(--ink-3); }}
    .kpi-value {{ font-size: clamp(1.35rem, 2.2vw, 1.75rem); font-weight:800; letter-spacing:-0.02em; margin-top:6px; color: var(--ink); font-variant-numeric: tabular-nums; white-space:nowrap; }}
    .kpi-value .unit {{ font-size:.95rem; font-weight:600; color: var(--ink-3); margin-left:3px; }}
    .kpi-sub {{ font-size:.78rem; color: var(--ink-2); margin-top:6px; }}
    /* executive hover / tap: lift with a deeper shadow, settle back over ~2s */
    @keyframes kpi-lift {{
        0%   {{ transform: translateY(0);    box-shadow: var(--shadow); }}
        12%  {{ transform: translateY(-6px); box-shadow: 0 18px 32px -14px rgba(21,35,27,.32), 0 2px 4px rgba(21,35,27,.06); }}
        55%  {{ transform: translateY(-6px); box-shadow: 0 18px 32px -14px rgba(21,35,27,.32), 0 2px 4px rgba(21,35,27,.06); }}
        100% {{ transform: translateY(0);    box-shadow: var(--shadow); }}
    }}
    .kpi:hover, .kpi:active {{ animation: kpi-lift 2s cubic-bezier(.22,.8,.25,1) 1 both; }}
    @media (prefers-reduced-motion: reduce) {{ .kpi:hover, .kpi:active {{ animation: none; }} }}

    /* ---- section cards (General) — the whole card is a button ---- */
    [class*="st-key-seccard_"] {{ position: relative; }}
    [class*="st-key-seccard_"] [data-testid="stVerticalBlock"] {{ gap: 0; }}
    [class*="st-key-open_"] {{ position:absolute; inset:0; z-index:2; }}
    [class*="st-key-open_"] button {{ position:absolute; inset:0; width:100%; height:100%; opacity:0; cursor:pointer; border:0; padding:0; margin:0; touch-action:manipulation; -webkit-tap-highlight-color: transparent; }}
    [class*="st-key-open_"] button:focus-visible {{ opacity:1; background:transparent; outline:3px solid var(--green); outline-offset:-3px; border-radius:var(--radius); }}
    [class*="st-key-open_"] button * {{ display:none; }}
    .sec-card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:14px 16px 12px; position:relative; overflow:hidden; min-height:138px; transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease; pointer-events:none; }}
    .sec-card:before {{ content:""; position:absolute; left:0; right:0; top:0; height:4px; background: var(--accent); }}
    [class*="st-key-seccard_"]:hover .sec-card {{ transform: translateY(-3px); box-shadow: 0 16px 28px -14px rgba(21,35,27,.3); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }}
    .sec-card-head {{ display:flex; align-items:center; gap:10px; }}
    .sec-card-icon {{ width:34px; height:34px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:1.1rem; background: color-mix(in srgb, var(--accent) 12%, white); flex:0 0 auto; }}
    .sec-card-name {{ font-weight:800; font-size:.95rem; line-height:1.2; letter-spacing:-0.005em; }}
    .sec-card-kind {{ font-size:.68rem; font-weight:700; letter-spacing:.04em; text-transform:uppercase; color: var(--ink-3); margin-top:2px; }}
    .sec-card-value {{ font-size:1.35rem; font-weight:800; letter-spacing:-0.02em; margin-top:10px; font-variant-numeric: tabular-nums; white-space:nowrap; }}
    .sec-card-value .unit {{ font-size:.85rem; font-weight:600; color:var(--ink-3); margin-left:3px; }}
    .sec-card-meta {{ display:flex; gap:14px; flex-wrap:wrap; font-size:.76rem; color: var(--ink-2); margin-top:6px; }}
    .sec-card-meta b {{ color: var(--ink); font-variant-numeric: tabular-nums; }}
    .sec-card-share {{ margin-top:10px; height:6px; border-radius:3px; background:#EEF1EC; overflow:hidden; }}
    .sec-card-share span {{ display:block; height:100%; background: var(--accent); border-radius:3px; }}
    .sec-card-open {{ position:absolute; right:14px; top:14px; font-size:.72rem; font-weight:700; color: var(--ink-3); opacity:0; transition: opacity .2s; }}
    [class*="st-key-seccard_"]:hover .sec-card-open {{ opacity:1; }}
    .sec-card.total {{ background: var(--green-soft); border-color:#CFE3D5; }}
    .sec-card.total .sec-card-value {{ color: var(--green-dark); }}

    /* ---- cards & tables ---- */
    .card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:14px 16px 10px; margin-top:8px; }}
    .card-title {{ font-size:.92rem; font-weight:800; letter-spacing:-0.005em; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .card-title .muted {{ font-weight:500; color: var(--ink-3); font-size:.8rem; }}
    .tbl-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; margin-top:8px; }}
    table.dt {{ width:100%; border-collapse:collapse; font-size:.88rem; min-width:520px; }}
    table.dt th {{ text-align:left; font-size:.72rem; font-weight:700; letter-spacing:.05em; text-transform:uppercase; color:var(--ink-3); padding:8px 10px; border-bottom:1px solid var(--border); white-space:nowrap; background:var(--surface); position:sticky; top:0; }}
    table.dt td {{ padding:9px 10px; border-bottom:1px solid #EEF1EC; vertical-align:middle; color:var(--ink); }}
    table.dt tr:last-child td {{ border-bottom:none; }}
    table.dt .num {{ text-align:right; font-variant-numeric: tabular-nums; white-space:nowrap; }}
    table.dt .dim {{ color: var(--ink-2); }}
    table.dt .date-cell {{ font-weight:700; white-space:nowrap; vertical-align:middle; color:var(--ink); width:1%; padding-right:18px; }}
    table.dt .total-cell {{ font-weight:800; font-size:.95rem; white-space:nowrap; font-variant-numeric: tabular-nums; color:var(--ink); border-left:1px solid #EEF1EC; border-right:1px solid #EEF1EC; width:1%; padding:9px 18px; background:#FBFCFA; }}
    table.dt thead th:nth-child(2) {{ color: var(--ink); }}
    table.dt tr.grand .total-cell {{ color: var(--green-dark); font-size:1rem; }}
    table.dt .date-cell small {{ display:block; font-weight:500; color:var(--ink-3); font-size:.74rem; margin-top:2px; }}
    table.dt tr.total td {{ font-weight:800; background: #F3F6F2; border-top:1px solid var(--border); }}
    table.dt tr.day-total td {{ font-weight:700; background: #F8FAF7; color: var(--ink); }}
    table.dt tr.grand td {{ font-weight:800; background: var(--green-soft); color: var(--green-dark); border-top:2px solid var(--green); }}
    table.dt tr.grand td {{ white-space:nowrap; }}
    .share-bar {{ display:inline-block; height:6px; border-radius:3px; background: var(--accent, var(--green)); vertical-align:middle; margin-right:8px; }}
    .pay-pill {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:.78rem; font-weight:600; background:#F3F4F6; color:#4B5563; white-space:nowrap; }}
    .pay-pill.comp {{ background:#FBE9E5; color:#8A2E1E; }}
    .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:8px; vertical-align:middle; }}
    .lg {{ display:flex; flex-wrap:wrap; gap:4px 14px; padding:2px 4px 8px; }}
    .lg-item {{ font-size:.78rem; color:var(--ink-2); white-space:nowrap; display:inline-flex; align-items:center; }}

    /* ---- empty state ---- */
    .empty {{ background:var(--surface); border:1px dashed var(--border); border-radius:var(--radius); padding:28px 20px; text-align:center; color:var(--ink-2); margin-top:8px; }}
    .empty b {{ color: var(--ink); }}

    /* ---- charts (bordered containers restyled as cards) ---- */
    .st-key-chart_share, .st-key-chart_daily {{ background:var(--surface); border:1px solid var(--border) !important; border-radius:var(--radius) !important; box-shadow:var(--shadow); padding:14px 12px 4px 16px !important; margin-top:8px; }}
    .st-key-chart_share [data-testid="stVerticalBlock"], .st-key-chart_daily [data-testid="stVerticalBlock"] {{ gap:0.2rem; }}

    /* ---- phones ---- */
    @media (max-width: 640px) {{
        .block-container {{ padding-top: 1.25rem !important; }}
        .st-key-tabs [data-testid="stRadioGroup"], .st-key-presets [data-testid="stRadioGroup"] {{
            flex-wrap:nowrap; overflow-x:auto; overflow-y:hidden; padding-bottom:10px; scrollbar-width:thin; -webkit-overflow-scrolling:touch;
        }}
        .cop-logo {{ width:180px; padding:8px 10px; }}
        .cop-head {{ gap:14px; }}
        .kpi-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap:8px; }}
        .kpi {{ padding:12px 12px 10px 16px; }}
        .kpi-value {{ font-size:1.2rem; white-space:normal; }}
        .kpi-label {{ font-size:.66rem; }}
        table.dt {{ font-size:.82rem; min-width:460px; }}
        .sec-title {{ font-size:1.05rem; }}
    }}
    """
    st.html(f"<style>{css}</style>")


# ----------------------------------------------------------------------------- header
@st.cache_data(show_spinner=False)
def _logo_data_uri(name: str = "cop17.jpg", width: int = 640) -> str | None:
    path = ASSETS / name
    if not path.exists():
        return None
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        ratio = width / img.width
        img = img.resize((width, max(1, int(img.height * ratio))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()
    except Exception:  # noqa: BLE001 — fall back to the raw bytes
        data = path.read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def render_header(ds: Dataset) -> None:
    logo = _logo_data_uri()
    logo_html = f'<img class="cop-logo" src="{logo}" alt="COP17 2026 Armenia">' if logo else ""
    if ds.is_empty:
        status = '<span class="chip"><span class="chip-dot red"></span>No data loaded</span>'
    else:
        origin = {"dropbox": "Dropbox", "local": "local file"}.get(ds.origin, "—")
        updated = pd.Timestamp(ds.loaded_at, unit="s", tz="UTC").tz_convert(config.TIMEZONE).strftime("%H:%M")
        status = f'<span class="chip"><span class="chip-dot"></span>{esc(origin)} · loaded {updated}</span>'
        status += f'<span class="chip"><span class="chip-dot"></span>{ds.daily_count} daily sheet{"s" if ds.daily_count != 1 else ""}</span>'
        if ds.period_count:
            status += f'<span class="chip"><span class="chip-dot amber"></span>{ds.period_count} period-total sheet{"s" if ds.period_count != 1 else ""}</span>'
        missing = [k for k, i in ds.info.items() if i.source == "missing"]
        if missing:
            status += f'<span class="chip"><span class="chip-dot red"></span>{len(missing)} sheet{"s" if len(missing) != 1 else ""} missing</span>'
        if ds.dmin and ds.dmax:
            status += f'<span class="chip"><span class="chip-dot grey"></span>Data {esc(dates.label(ds.dmin, ds.dmax))}</span>'
    st.html(
        f'<div class="cop-head">{logo_html}'
        f'<div><div class="cop-title">{esc(config.APP_TITLE)}</div>'
        f'<div class="cop-sub">{esc(config.APP_SUBTITLE)}</div>'
        f'<div class="cop-status">{status}</div></div></div>'
    )


# ----------------------------------------------------------------------------- navigation & dates
def _request_scroll_top() -> None:
    st.session_state["scroll_top"] = True


def render_tabs() -> str:
    """The tab bar. Any tab change (click, or a card's callback) lands the page at the very top."""
    labels = [s.label for s in config.SECTIONS]
    with st.container(key="tabs"):
        choice = st.radio("Section", labels, horizontal=True, label_visibility="collapsed", key="section",
                          width="stretch", on_change=_request_scroll_top)
    return config.SECTIONS[labels.index(choice)].key


def render_date_controls(ds: Dataset) -> tuple[date, date]:
    dmin, dmax = ds.dmin, ds.dmax
    dates.init_state(dmin, dmax)
    left, right = st.columns([5, 1.6], vertical_alignment="center")
    with left:
        with st.container(key="presets"):
            st.radio("Period", config.PRESETS, horizontal=True, label_visibility="collapsed", key="preset", width="stretch")
        preset = st.session_state["preset"]
        if preset == config.PRESET_CUSTOM:
            c1, c2 = st.columns(2)
            with c1:
                st.date_input("Start date", key="custom_start", format="DD.MM.YYYY")
            with c2:
                st.date_input("End date", key="custom_end", format="DD.MM.YYYY")
    start, end = dates.resolve(preset, dmin, dmax)
    with right:
        n_days = (end - start).days + 1
        st.html(f'<div style="text-align:right"><span class="range-chip">📅 {esc(dates.label(start, end))}'
                f' <span style="opacity:.7">· {n_days} day{"s" if n_days != 1 else ""}</span></span></div>')
    return start, end


# ----------------------------------------------------------------------------- section header & KPIs
def render_section_head(section: config.Section, info: SectionInfo | None, ds: Dataset) -> None:
    if section.kind == "global":
        meta = "All LOTs and sections combined · compliments excluded"
        badge = '<span class="badge badge-live">Combined</span>'
    elif section.kind == "compliments":
        meta = "Free-of-charge orders (payment type «без оплаты») across every LOT"
        badge = ""
    elif info is None or info.source == "missing":
        meta = info.note if info else "Sheet not found in the workbook."
        badge = '<span class="badge badge-missing">Sheet missing</span>'
    elif info.source == "period":
        p = ds.periods[section.key]
        meta = f"Period-summary sheet «{info.sheet}» · {dates.label(p.start, p.end)}"
        badge = '<span class="badge badge-period">Period total</span>'
    else:
        meta = f"Live · workbook sheet «{info.sheet}» · {info.rows} rows parsed"
        badge = '<span class="badge badge-live">Daily data</span>'
    st.html(
        f'<div class="sec-head" style="--accent:{section.color}">'
        f'<div class="sec-icon">{section.icon}</div>'
        f'<div style="flex:1;min-width:0"><div class="sec-title">{esc(section.key)}</div><div class="sec-meta">{esc(meta)}</div></div>'
        f'{badge}</div>'
    )


def render_kpis(k: dict, section: config.Section, start: date, end: date, periods: list[PeriodSummary]) -> None:
    accent = section.color
    is_comp = section.kind == "compliments"
    single_period = section.kind == "sheet" and len(periods) == 1 and not k["days"]
    if single_period:
        p = periods[0]
        sales_sub = f"Period total · {esc(dates.label(p.start, p.end))}"
    elif k["days"]:
        sales_sub = f"{k['days']} trading day{'s' if k['days'] != 1 else ''} · {esc(dates.label(start, end))}"
        if periods:
            sales_sub += f" · incl. {len(periods)} period total{'s' if len(periods) != 1 else ''}"
    else:
        sales_sub = f"Period totals · {esc(dates.label(start, end))}"
    checks_sub = "Чеков · orders in the period"
    aov_sub = "Net sales ÷ checks"
    if k["checks_partial"] and single_period:
        checks_sub = "No check count on this sheet"
        aov_sub = "Needs a check count"
    elif k["checks_partial"]:
        names = ", ".join(p.section for p in periods if p.checks is None)
        checks_sub = f"Not recorded for: {esc(names)}"
        aov_sub = "Sales ÷ checks, sections with check counts only"
    cards = [
        ("Compliments value" if is_comp else "Total Net Sales", f"{fmt_n(k['sales'])}<span class='unit'>{config.CURRENCY}</span>", sales_sub),
        ("Total Checks", fmt_n(k["checks"]) if k["checks"] else "—", checks_sub),
        ("Average Order Value", (f"{fmt_n(k['aov'])}<span class='unit'>{config.CURRENCY}</span>" if k["checks"] else "—"), aov_sub),
    ]
    if k["has_discount"]:
        rate = k["discount"] / k["gross"] if k["gross"] else 0.0
        cards.append(("Total Discounts", f"{fmt_n(k['discount'])}<span class='unit'>{config.CURRENCY}</span>",
                      f"{fmt_pct(rate)} of gross · before discounts: {fmt_money(k['gross'])}"))
    body = "".join(
        f'<div class="kpi" style="--accent:{accent}"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>'
        for label, value, sub in cards
    )
    st.html(f'<div class="kpi-grid">{body}</div>')


def render_excluded_note(excluded: list[PeriodSummary]) -> None:
    """Period totals that touch the selected range but are not fully inside it are left out, and say so."""
    if not excluded:
        return
    parts = ", ".join(f"{esc(p.section)} ({esc(dates.label(p.start, p.end))})" for p in excluded)
    st.html(f'<div class="note">ⓘ Period totals are single figures for their whole period, so they are counted only when '
            f'the selected range covers that period in full. Not included here: {parts}.</div>')


def render_period_card(p: PeriodSummary, info: SectionInfo | None) -> None:
    """The column-C summary of a period sheet: date/period → total → line / checks."""
    checks = fmt_n(p.checks) if p.checks else "—"
    if p.entries:
        dated = any(d for d, _, _ in p.entries)
        rows = "".join(
            "<tr>" + (f'<td class="date-cell">{esc(fmt_day(d)) if d else "—"}</td>' if dated else "")
            + f'<td class="total-cell">{fmt_n(amount)}</td><td>{esc(label)}</td></tr>'
            for d, label, amount in p.entries
        )
        rows += ("<tr class=\"grand\">" + ('<td>Total</td>' if dated else "")
                 + f'<td class="total-cell">{fmt_n(p.total)}</td><td>{"Total · " if not dated else ""}{esc(p.total_label) or "column C"}</td></tr>')
        date_th = "<th>Date</th>" if dated else ""
        table = (f'<div class="tbl-wrap"><table class="dt"><thead><tr>{date_th}<th>Total sales (֏)</th><th>Line</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>')
    else:
        table = (f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Period</th><th>Total sales (֏)</th><th class="num">Checks</th></tr></thead>'
                 f'<tbody><tr class="grand"><td class="date-cell">{esc(dates.label(p.start, p.end))}</td><td class="total-cell">{fmt_n(p.total)}</td>'
                 f'<td class="num">{checks}</td></tr></tbody></table></div>')
    src = f"sheet «{info.sheet}»" if info and info.sheet else "workbook"
    period_note = "" if p.period_from_sheet else " · no dates found on the sheet, so the period is the data range"
    st.html(
        f'<div class="card"><div class="card-title">Period summary<span class="muted">column C of {esc(src)} · '
        f'{esc(dates.label(p.start, p.end))}{period_note} · {config.CURRENCY}</span></div>{table}</div>'
    )


# ----------------------------------------------------------------------------- tables
def _pay(label: str, comp: bool) -> str:
    return f'<span class="pay-pill{" comp" if comp else ""}">{esc(label)}</span>'


def render_overall_totals(totals: pd.DataFrame, show_discount: bool, title: str = "Overall totals",
                          subtitle: str = "by payment type") -> None:
    """Payment type → total sales → checks → share → [discount]."""
    if totals.empty:
        return
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for _, r in totals.iterrows():
        comp = bool(r.get("is_compliment", False)) or "без оплаты" in str(r["payment_type"]).casefold()
        width = int(round(float(r["share"]) * 120))
        disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
        rows.append(
            f'<tr><td>{_pay(r["payment_type"], comp)}</td><td class="total-cell">{fmt_n(r["sales"])}</td>'
            f'<td class="num">{fmt_n(r["checks"])}</td>'
            f'<td class="num"><span class="share-bar" style="width:{width}px"></span>{fmt_pct(r["share"])}</td>{disc_td}</tr>'
        )
    t_checks, t_sales, t_disc = totals["checks"].sum(), totals["sales"].sum(), totals["discount"].sum()
    disc_tot = f'<td class="num">{fmt_n(t_disc)}</td>' if show_discount else ""
    rows.append(f'<tr class="grand"><td>Total</td><td class="total-cell">{fmt_n(t_sales)}</td>'
                f'<td class="num">{fmt_n(t_checks)}</td><td class="num">100%</td>{disc_tot}</tr>')
    st.html(
        f'<div class="card"><div class="card-title">{esc(title)}<span class="muted">{esc(subtitle)} · {config.CURRENCY}</span></div>'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Payment type</th><th>Total sales (֏)</th><th class="num">Checks</th>'
        f'<th class="num">Share</th>{disc_th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def render_grand_totals(k: dict, periods: list[PeriodSummary]) -> str:
    """Overall grand totals strip: daily sections + period totals = grand total."""
    if not periods:
        return (f'<div class="gt"><span class="gt-item"><span class="gt-label">Grand total</span>'
                f'<span class="gt-value">{fmt_money(k["sales"])}</span></span>'
                f'<span class="gt-item"><span class="gt-label">Checks</span><span class="gt-value">{fmt_n(k["checks"])}</span></span></div>')
    names = ", ".join(p.section for p in periods)
    return (f'<div class="gt"><span class="gt-item"><span class="gt-label">Daily sections</span>'
            f'<span class="gt-value">{fmt_money(k["daily_sales"])}</span></span>'
            f'<span class="gt-plus">+</span>'
            f'<span class="gt-item"><span class="gt-label">Period totals · {esc(names)}</span>'
            f'<span class="gt-value">{fmt_money(k["period_sales"])}</span></span>'
            f'<span class="gt-plus">=</span>'
            f'<span class="gt-item gt-grand"><span class="gt-label">Grand total</span>'
            f'<span class="gt-value">{fmt_money(k["sales"])}</span></span></div>')


def render_daily_table(pivot: pd.DataFrame, pay_cols: list[str], show_discount: bool, k: dict,
                       periods: list[PeriodSummary]) -> None:
    """One row per day: DATE → TOTAL SALES (֏) → BANK CARDS → CASH → BANK TRANSFERS / INVOICES → CHECKS."""
    if pivot.empty:
        return
    pay_th = "".join(f'<th class="num">{esc(c)}</th>' for c in pay_cols)
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for _, r in pivot.iterrows():
        d = r["date"]
        pay_td = "".join(f'<td class="num">{fmt_n(r[c]) if c in r and r[c] else "—"}</td>' for c in pay_cols)
        disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
        rows.append(f'<tr><td class="date-cell">{esc(fmt_day(d))}</td><td class="total-cell">{fmt_n(r["sales"])}</td>'
                    f'{pay_td}<td class="num">{fmt_n(r["checks"])}</td>{disc_td}</tr>')
    pay_tot = "".join(f'<td class="num">{fmt_n(pivot[c].sum()) if c in pivot and pivot[c].sum() else "—"}</td>' for c in pay_cols)
    disc_tot = f'<td class="num">{fmt_n(pivot["discount"].sum())}</td>' if show_discount else ""
    label = "Period total" if not periods else "Daily sections total"
    rows.append(f'<tr class="grand"><td>{label} · {len(pivot)} day{"s" if len(pivot) != 1 else ""}</td>'
                f'<td class="total-cell">{fmt_n(pivot["sales"].sum())}</td>{pay_tot}'
                f'<td class="num">{fmt_n(pivot["checks"].sum())}</td>{disc_tot}</tr>')
    st.html(
        f'<div class="card"><div class="card-title">Day-by-day breakdown<span class="muted">sales per payment type · {config.CURRENCY}</span></div>'
        f'{render_grand_totals(k, periods)}'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Date</th><th>Total sales (֏)</th>{pay_th}'
        f'<th class="num">Checks</th>{disc_th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def render_section_table(sections: pd.DataFrame, show_discount: bool, title: str = "Sales by section") -> None:
    """Section → total sales → checks → AOV → share → [discount]."""
    if sections.empty:
        return
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for _, r in sections.iterrows():
        sec = config.SECTION_BY_KEY.get(r["section"])
        color = config.CHART_COLORS.get(r["section"], T["ink_3"])
        icon = sec.icon if sec else ""
        tag = ""
        if r["kind"] == "period" and r["period"]:
            tag = f'<span class="tag-period">Period total · {esc(dates.label(*r["period"]))}</span>'
        width = int(round(float(r["share"]) * 120))
        disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
        checks = fmt_n(r["checks"]) if pd.notna(r["checks"]) and r["checks"] else "—"
        aov = fmt_n(r["aov"]) if pd.notna(r["aov"]) and r["aov"] else "—"
        rows.append(
            f'<tr><td><span class="dot" style="background:{color}"></span>{icon} <b>{esc(r["section"])}</b>{tag}</td>'
            f'<td class="total-cell">{fmt_n(r["sales"])}</td>'
            f'<td class="num">{checks}</td><td class="num">{aov}</td>'
            f'<td class="num"><span class="share-bar" style="width:{width}px;--accent:{color}"></span>{fmt_pct(r["share"])}</td>{disc_td}</tr>'
        )
    t_checks = sections["checks"].fillna(0).sum()
    t_sales, t_disc = sections["sales"].sum(), sections["discount"].sum()
    disc_tot = f'<td class="num">{fmt_n(t_disc)}</td>' if show_discount else ""
    aov_sales = sections.loc[sections["checks"].fillna(0) > 0, "sales"].sum()
    aov = fmt_n(aov_sales / t_checks) if t_checks else "—"
    rows.append(f'<tr class="grand"><td>All sections</td><td class="total-cell">{fmt_n(t_sales)}</td>'
                f'<td class="num">{fmt_n(t_checks) if t_checks else "—"}</td><td class="num">{aov}</td><td class="num">100%</td>{disc_tot}</tr>')
    st.html(
        f'<div class="card"><div class="card-title">{esc(title)}<span class="muted">LOTs and event sections · {config.CURRENCY}</span></div>'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Section</th><th>Total sales (֏)</th><th class="num">Checks</th>'
        f'<th class="num">AOV</th><th class="num">Share</th>{disc_th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    )


# ----------------------------------------------------------------------------- section cards (General)
def render_section_cards(sections: pd.DataFrame, k: dict, on_pick, per_row: int = 3) -> None:
    """One clickable card per section (+ a grand-total tile). Clicking opens that section's tab."""
    if sections.empty:
        return
    st.html('<div class="card-title" style="margin:14px 0 2px">Sales by section'
            '<span class="muted">click a card to open its tab</span></div>')
    rows = list(sections.itertuples(index=False))
    cards = [("section", r) for r in rows] + [("total", None)]
    for start_i in range(0, len(cards), per_row):
        cols = st.columns(per_row)
        for j, (kind, r) in enumerate(cards[start_i:start_i + per_row]):
            i = start_i + j
            with cols[j], st.container(key=f"seccard_{i}"):
                if kind == "total":
                    st.html(_total_card_html(k, len(rows)))
                    st.button("Back to top", key=f"open_{i}", on_click=on_pick, args=(None,))
                else:
                    st.html(_section_card_html(r))
                    st.button(f"Open {r.section}", key=f"open_{i}", on_click=on_pick, args=(r.section,))


def _section_card_html(r) -> str:
    sec = config.SECTION_BY_KEY.get(r.section)
    icon = sec.icon if sec else "▪"
    color = config.CHART_COLORS.get(r.section, T["ink_3"])
    if r.kind == "period" and r.period:
        kind = f"Period total · {esc(dates.label(*r.period))}"
    else:
        kind = "Daily sales"
    checks = fmt_n(r.checks) if pd.notna(r.checks) and r.checks else "—"
    aov = fmt_n(r.aov) if pd.notna(r.aov) and r.aov else "—"
    disc = f'<span>Discount <b>{fmt_n(r.discount)}</b></span>' if r.discount else ""
    pct = max(0.0, min(100.0, float(r.share) * 100))
    return (
        f'<div class="sec-card" style="--accent:{color}">'
        f'<div class="sec-card-head"><div class="sec-card-icon">{icon}</div>'
        f'<div><div class="sec-card-name">{esc(r.section)}</div><div class="sec-card-kind">{kind}</div></div></div>'
        f'<div class="sec-card-open">Open ↗</div>'
        f'<div class="sec-card-value">{fmt_n(r.sales)}<span class="unit">{config.CURRENCY}</span></div>'
        f'<div class="sec-card-meta"><span>Checks <b>{checks}</b></span><span>AOV <b>{aov}</b></span>'
        f'<span>Share <b>{fmt_pct(r.share)}</b></span>{disc}</div>'
        f'<div class="sec-card-share"><span style="width:{pct:.1f}%"></span></div></div>'
    )


def _total_card_html(k: dict, n_sections: int) -> str:
    checks = fmt_n(k["checks"]) if k["checks"] else "—"
    aov = fmt_n(k["aov"]) if k["checks"] else "—"
    return (
        f'<div class="sec-card total" style="--accent:{T["green"]}">'
        f'<div class="sec-card-head"><div class="sec-card-icon">Σ</div>'
        f'<div><div class="sec-card-name">All sections</div><div class="sec-card-kind">{n_sections} sections · grand total</div></div></div>'
        f'<div class="sec-card-value">{fmt_n(k["sales"])}<span class="unit">{config.CURRENCY}</span></div>'
        f'<div class="sec-card-meta"><span>Checks <b>{checks}</b></span><span>AOV <b>{aov}</b></span>'
        f'<span>Share <b>100%</b></span></div>'
        f'<div class="sec-card-share"><span style="width:100%"></span></div></div>'
    )


def scroll_to_top() -> None:
    """Land the app at the very top. Streamlit scrolls section[data-testid=stMain], not the window, and it
    keeps re-rendering for a moment after a tab switch, so the scroll is repeated for ~1.2 s."""
    components.html(
        """<script>
        (function () {
          var win = window.parent, doc = win.document;
          function go(behavior) {
            var targets = [doc.querySelector('section[data-testid="stMain"]'), doc.querySelector('section.main'),
                           doc.querySelector('[data-testid="stAppViewContainer"]'), doc.scrollingElement, doc.documentElement, doc.body];
            targets.forEach(function (el) {
              if (!el) { return; }
              try { el.scrollTo({top: 0, left: 0, behavior: behavior}); } catch (e) { el.scrollTop = 0; }
            });
            try { win.scrollTo({top: 0, behavior: behavior}); } catch (e) { win.scrollTo(0, 0); }
          }
          go('smooth');
          var n = 0, t = setInterval(function () { go(++n < 3 ? 'smooth' : 'auto'); if (n >= 8) { clearInterval(t); } }, 150);
        })();
        </script>""",
        height=0,
    )


# ----------------------------------------------------------------------------- charts
_PLOT_FONT = dict(family="Inter, -apple-system, Segoe UI, Roboto, sans-serif", color=T["ink"], size=12)


def _html_legend(labels: list[str], colors: list[str]) -> None:
    """Shared legend rendered in HTML so it wraps cleanly at any width (Plotly's would overlap the axis)."""
    items = "".join(f'<span class="lg-item"><span class="dot" style="background:{c}"></span>{esc(l)}</span>'
                    for l, c in zip(labels, colors))
    st.html(f'<div class="lg">{items}</div>')


def render_charts(sections: pd.DataFrame, by_day: pd.DataFrame) -> None:
    if sections.empty:
        return
    labels = sections["section"].tolist()
    colors = [config.CHART_COLORS.get(s, T["ink_3"]) for s in labels]
    total = float(sections["sales"].sum())
    c1, c2 = st.columns([1, 1.6])
    with c1, st.container(border=True, key="chart_share"):
        st.html('<div class="card-title">Share of sales<span class="muted">by section</span></div>')
        fig = go.Figure(go.Pie(
            labels=labels, values=sections["sales"].round(0).tolist(), hole=0.64, sort=False, direction="clockwise",
            marker=dict(colors=colors, line=dict(color="#FFFFFF", width=2)),
            textposition="inside", insidetextorientation="horizontal",
            texttemplate=["%{percent:.0%}" if v / max(total, 1) >= 0.06 else "" for v in sections["sales"]],
            textfont=dict(color="#FFFFFF", size=12),
            hovertemplate="%{label}<br>%{value:,.0f} ֏ · %{percent:.1%}<extra></extra>",
        ))
        fig.update_layout(
            showlegend=False, margin=dict(l=6, r=6, t=6, b=6), height=290, font=_PLOT_FONT,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            annotations=[dict(text=f"<b>{fmt_n(total)}</b><br><span style='font-size:11px;color:{T['ink_3']}'>֏ total</span>",
                              x=0.5, y=0.5, showarrow=False, font=dict(size=15, color=T["ink"]))],
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        _html_legend(labels, colors)
    with c2, st.container(border=True, key="chart_daily"):
        st.html('<div class="card-title">Daily sales<span class="muted">daily sheets, stacked by section</span></div>')
        fig = go.Figure()
        daily_labels = [l for l, c in zip(labels, colors) if l in set(by_day["section"])]
        daily_colors = [c for l, c in zip(labels, colors) if l in set(by_day["section"])]
        for sec_key, color in zip(daily_labels, daily_colors):
            part = by_day[by_day["section"] == sec_key].sort_values("date")
            if part.empty:
                continue
            fig.add_bar(
                x=[pd.Timestamp(d) for d in part["date"]], y=part["sales"].round(0), name=sec_key,
                marker=dict(color=color, line=dict(color="#FFFFFF", width=1)),
                hovertemplate="%{x|%a %d %b}<br>" + esc(sec_key) + ": %{y:,.0f} ֏<extra></extra>",
            )
        fig.update_layout(
            barmode="stack", bargap=0.28, height=290, margin=dict(l=6, r=6, t=6, b=6), font=_PLOT_FONT,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
            xaxis=dict(tickformat="%d %b", showgrid=False, dtick=86400000, tickfont=dict(size=11)),
            yaxis=dict(gridcolor="#EEF1EC", zeroline=False, tickformat="~s", tickfont=dict(size=11, color=T["ink_3"])),
            hovermode="x unified",
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        _html_legend(daily_labels, daily_colors)


# ----------------------------------------------------------------------------- misc
def render_empty(section: config.Section, start: date, end: date, ds: Dataset) -> None:
    what = "compliments" if section.kind == "compliments" else "sales"
    where = "any section" if section.kind in ("global", "compliments") else section.key
    hint = f" The workbook covers {esc(dates.label(ds.dmin, ds.dmax))}." if ds.dmin and ds.dmax else ""
    st.html(f'<div class="empty">No {what} recorded for <b>{esc(dates.label(start, end))}</b> in {esc(where)}.{hint}</div>')
    st.button("Show full event period", key="show_full", on_click=dates.set_full_period)


def render_raw(records: pd.DataFrame, section_key: str, start: date, end: date) -> None:
    with st.expander(f"Raw records · {len(records)} rows"):
        st.dataframe(records, width="stretch", hide_index=True,
                     column_config={"Чеков": st.column_config.NumberColumn(format="%d"),
                                    "Payment": st.column_config.TextColumn(help="Bank Cards = POS Arcus + Банковские карты · Cash = Наличные"),
                                    "Сумма со скидкой": st.column_config.NumberColumn(format="%d"),
                                    "Сумма скидки": st.column_config.NumberColumn(format="%d")})
        slug = re.sub(r"[^A-Za-z0-9]+", "_", section_key).strip("_").lower() or "section"
        fname = f"cop17_{slug}_{start:%Y%m%d}-{end:%Y%m%d}.csv"
        st.download_button("Download CSV", data=lambda: records.to_csv(index=False).encode("utf-8-sig"),
                           file_name=fname, mime="text/csv", on_click="ignore", key="dl_csv")
