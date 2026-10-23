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
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import config, dates
from .config import THEME as T
from .data import Dataset, SectionInfo

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
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ----------------------------------------------------------------------------- theme
def inject_css() -> None:
    css = f"""
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    /* ---- clean interface overrides (requested) ---- */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    header {{visibility: hidden;}}
    [data-testid="stHeader"] {{display: none !important;}}
    [data-testid="stToolbar"] {{display: none !important;}}
    .viewerBadge_container__1s52n, .stAppViewerFooter {{display: none !important;}}
    [data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stAppToolbar"] {{display: none !important;}}
    .block-container {{
        padding-top: 2rem !important;
        padding-bottom: 5rem !important;
        padding-left: clamp(1rem, 2.5vw, 2.5rem) !important;
        padding-right: clamp(1rem, 2.5vw, 2.5rem) !important;
        max-width: 100% !important;
    }}
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
    .stApp, .stApp p, .stApp div, .stApp span, .stApp td, .stApp th {{
        font-family: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }}
    .stApp {{ color: var(--ink); }}
    .stApp a {{ color: var(--blue); }}
    [data-testid="stVerticalBlock"] {{ gap: 0.6rem; }}

    /* ---- header ---- */
    .cop-head {{ display:flex; align-items:center; gap:18px; flex-wrap:wrap; }}
    .cop-logo {{ height:64px; width:auto; border-radius:12px; border:1px solid var(--border); background:#fff; padding:6px 10px; object-fit:contain; }}
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
    .st-key-tabs [data-testid="stRadioOption"], .st-key-presets [data-testid="stRadioOption"] {{
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
    .badge-sample {{ background: var(--gold-soft); color: #7A5306; }}
    .badge-missing {{ background: #FBE9E5; color: #8A2E1E; }}
    .badge-mixed {{ background: var(--blue-soft); color: #244B70; }}

    /* ---- KPI cards ---- */
    .kpi-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap:12px; margin: 6px 0 4px; }}
    .kpi {{ position:relative; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px 18px 14px 20px; box-shadow:var(--shadow); overflow:hidden; min-width:0; }}
    .kpi:before {{ content:""; position:absolute; left:0; top:12px; bottom:12px; width:4px; border-radius:0 4px 4px 0; background: var(--accent); }}
    .kpi-label {{ font-size:.74rem; font-weight:700; letter-spacing:.06em; text-transform:uppercase; color: var(--ink-3); }}
    .kpi-value {{ font-size: clamp(1.35rem, 2.2vw, 1.75rem); font-weight:800; letter-spacing:-0.02em; margin-top:6px; color: var(--ink); font-variant-numeric: tabular-nums; white-space:nowrap; }}
    .kpi-value .unit {{ font-size:.95rem; font-weight:600; color: var(--ink-3); margin-left:3px; }}
    .kpi-sub {{ font-size:.78rem; color: var(--ink-2); margin-top:6px; }}

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
    table.dt .date-cell {{ font-weight:700; white-space:nowrap; vertical-align:top; color:var(--ink); border-right:1px solid #EEF1EC; width:1%; }}
    table.dt .date-cell small {{ display:block; font-weight:500; color:var(--ink-3); font-size:.74rem; margin-top:2px; }}
    table.dt tr.total td {{ font-weight:800; background: #F3F6F2; border-top:1px solid var(--border); }}
    table.dt tr.day-total td {{ font-weight:700; background: #F8FAF7; color: var(--ink); }}
    table.dt tr.grand td {{ font-weight:800; background: var(--green-soft); color: var(--green-dark); border-top:2px solid var(--green); }}
    .share-bar {{ display:inline-block; height:6px; border-radius:3px; background: var(--accent, var(--green)); vertical-align:middle; margin-right:8px; }}
    .pay-pill {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:.78rem; font-weight:600; background:#F3F4F6; color:#4B5563; white-space:nowrap; }}
    .pay-pill.comp {{ background:#FBE9E5; color:#8A2E1E; }}
    .tag-sample {{ display:inline-block; font-size:.66rem; font-weight:700; letter-spacing:.04em; text-transform:uppercase; padding:2px 7px; border-radius:6px; background:var(--gold-soft); color:#7A5306; margin-left:8px; vertical-align:middle; }}
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
        .cop-logo {{ height:48px; }}
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
def _logo_data_uri(name: str = "cop17.jpg", width: int = 420) -> str | None:
    path = ASSETS / name
    if not path.exists():
        return None
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        ratio = width / img.width
        img = img.resize((width, max(1, int(img.height * ratio))))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        data = buf.getvalue()
    except Exception:  # noqa: BLE001 — fall back to the raw bytes
        data = path.read_bytes()
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def render_header(ds: Dataset) -> None:
    logo = _logo_data_uri()
    logo_html = f'<img class="cop-logo" src="{logo}" alt="COP17 2026 Armenia">' if logo else ""
    if ds.df.empty:
        status = '<span class="chip"><span class="chip-dot red"></span>No data loaded</span>'
    else:
        origin = {"dropbox": "Dropbox", "local": "local file"}.get(ds.origin, "—")
        updated = pd.Timestamp(ds.loaded_at, unit="s", tz="UTC").tz_convert(config.TIMEZONE).strftime("%H:%M")
        status = (
            f'<span class="chip"><span class="chip-dot"></span>{esc(origin)} · loaded {updated}</span>'
            f'<span class="chip"><span class="chip-dot"></span>{ds.live_count} live sheet{"s" if ds.live_count != 1 else ""}</span>'
        )
        if ds.sample_count:
            status += f'<span class="chip"><span class="chip-dot amber"></span>{ds.sample_count} sample section{"s" if ds.sample_count != 1 else ""}</span>'
        if ds.dmin and ds.dmax:
            status += f'<span class="chip"><span class="chip-dot grey"></span>Data {esc(dates.label(ds.dmin, ds.dmax))}</span>'
    st.html(
        f'<div class="cop-head">{logo_html}'
        f'<div><div class="cop-title">{esc(config.APP_TITLE)}</div>'
        f'<div class="cop-sub">{esc(config.APP_SUBTITLE)}</div>'
        f'<div class="cop-status">{status}</div></div></div>'
    )


# ----------------------------------------------------------------------------- navigation & dates
def render_tabs() -> str:
    labels = [s.label for s in config.SECTIONS]
    with st.container(key="tabs"):
        choice = st.radio("Section", labels, horizontal=True, label_visibility="collapsed", key="section")
    return config.SECTIONS[labels.index(choice)].key


def render_date_controls(ds: Dataset) -> tuple[date, date]:
    dmin, dmax = ds.dmin, ds.dmax
    dates.init_state(dmin, dmax)
    left, right = st.columns([5, 1.6], vertical_alignment="center")
    with left:
        with st.container(key="presets"):
            st.radio("Period", config.PRESETS, horizontal=True, label_visibility="collapsed", key="preset")
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
def render_section_head(section: config.Section, info: SectionInfo | None, k: dict) -> None:
    if section.kind == "global":
        meta = "All LOTs and sections combined · compliments excluded"
        badge = '<span class="badge badge-mixed">Combined</span>' if k.get("has_sample") else '<span class="badge badge-live">Live data</span>'
    elif section.kind == "compliments":
        meta = "Free-of-charge orders (payment type «без оплаты») across every section"
        badge = ""
    elif info is None or info.source == "missing":
        meta = (info.note if info else "Sheet not found in the workbook.")
        badge = '<span class="badge badge-missing">Sheet missing</span>'
    elif info.source == "sample":
        meta = "No sheet in the workbook yet — generated sample data (replaced automatically once the sheet exists)"
        badge = '<span class="badge badge-sample">Sample data</span>'
    else:
        meta = f"Live · workbook sheet «{info.sheet}» · {info.rows} rows parsed"
        badge = '<span class="badge badge-live">Live data</span>'
    st.html(
        f'<div class="sec-head" style="--accent:{section.color}">'
        f'<div class="sec-icon">{section.icon}</div>'
        f'<div style="flex:1;min-width:0"><div class="sec-title">{esc(section.key)}</div><div class="sec-meta">{esc(meta)}</div></div>'
        f'{badge}</div>'
    )


def render_kpis(k: dict, section: config.Section, start: date, end: date) -> None:
    accent = section.color
    is_comp = section.kind == "compliments"
    period = f"{k['days']} trading day{'s' if k['days'] != 1 else ''} · {esc(dates.label(start, end))}"
    cards = [
        ("Compliments value" if is_comp else "Total Sales", f"{fmt_n(k['sales'])}<span class='unit'>{config.CURRENCY}</span>", period),
        ("Total Checks", fmt_n(k["checks"]), "Чеков · orders in the period"),
        ("Average Order Value", f"{fmt_n(k['aov'])}<span class='unit'>{config.CURRENCY}</span>", "Sales ÷ checks"),
    ]
    if k["has_discount"]:
        rate = k["discount"] / k["gross"] if k["gross"] else 0.0
        cards.append(("Total Discounts", f"{fmt_n(k['discount'])}<span class='unit'>{config.CURRENCY}</span>",
                      f"{fmt_pct(rate)} of gross · before: {fmt_money(k['gross'])}"))
    body = "".join(
        f'<div class="kpi" style="--accent:{accent}"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>'
        for label, value, sub in cards
    )
    st.html(f'<div class="kpi-grid">{body}</div>')


# ----------------------------------------------------------------------------- tables
def _pay(label: str, comp: bool) -> str:
    return f'<span class="pay-pill{" comp" if comp else ""}">{esc(label)}</span>'


def render_overall_totals(totals: pd.DataFrame, show_discount: bool, title: str = "Overall totals") -> None:
    if totals.empty:
        return
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for _, r in totals.iterrows():
        comp = bool(r.get("is_compliment", False)) or "без оплаты" in str(r["payment_type"]).casefold()
        width = int(round(float(r["share"]) * 120))
        disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
        rows.append(
            f'<tr><td>{_pay(r["payment_type"], comp)}</td><td class="num">{fmt_n(r["checks"])}</td>'
            f'<td class="num">{fmt_n(r["sales"])}</td>{disc_td}'
            f'<td class="num"><span class="share-bar" style="width:{width}px"></span>{fmt_pct(r["share"])}</td></tr>'
        )
    t_checks, t_sales, t_disc = totals["checks"].sum(), totals["sales"].sum(), totals["discount"].sum()
    disc_tot = f'<td class="num">{fmt_n(t_disc)}</td>' if show_discount else ""
    rows.append(f'<tr class="grand"><td>Total</td><td class="num">{fmt_n(t_checks)}</td>'
                f'<td class="num">{fmt_n(t_sales)}</td>{disc_tot}<td class="num">100%</td></tr>')
    st.html(
        f'<div class="card"><div class="card-title">{esc(title)}<span class="muted">by payment type · {config.CURRENCY}</span></div>'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Payment type</th><th class="num">Checks</th>'
        f'<th class="num">Sales</th>{disc_th}<th class="num">Share</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def render_daily_table(daily: pd.DataFrame, show_discount: bool) -> None:
    if daily.empty:
        return
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for day, block in daily.groupby("date", sort=True):
        n = len(block)
        first = True
        for _, r in block.iterrows():
            comp = "без оплаты" in str(r["payment_type"]).casefold()
            disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
            date_td = (f'<td class="date-cell" rowspan="{n + 1}">{esc(fmt_day(day))}<small>{day.strftime("%d.%m.%Y")}</small></td>'
                       if first else "")
            first = False
            rows.append(f'<tr>{date_td}<td>{_pay(r["payment_type"], comp)}</td><td class="num">{fmt_n(r["checks"])}</td>'
                        f'<td class="num">{fmt_n(r["sales"])}</td>{disc_td}</tr>')
        d_disc = f'<td class="num">{fmt_n(block["discount"].sum())}</td>' if show_discount else ""
        rows.append(f'<tr class="day-total"><td class="dim">Day total</td><td class="num">{fmt_n(block["checks"].sum())}</td>'
                    f'<td class="num">{fmt_n(block["sales"].sum())}</td>{d_disc}</tr>')
    g_disc = f'<td class="num">{fmt_n(daily["discount"].sum())}</td>' if show_discount else ""
    rows.append(f'<tr class="grand"><td colspan="2">Period total · {daily["date"].nunique()} days</td>'
                f'<td class="num">{fmt_n(daily["checks"].sum())}</td><td class="num">{fmt_n(daily["sales"].sum())}</td>{g_disc}</tr>')
    st.html(
        f'<div class="card"><div class="card-title">Day-by-day breakdown<span class="muted">date × payment type · {config.CURRENCY}</span></div>'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Date</th><th>Payment type</th><th class="num">Checks</th>'
        f'<th class="num">Sales</th>{disc_th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
    )


def render_section_table(sections: pd.DataFrame, info: dict[str, SectionInfo], show_discount: bool) -> None:
    if sections.empty:
        return
    disc_th = '<th class="num">Discount</th>' if show_discount else ""
    rows = []
    for _, r in sections.iterrows():
        sec = config.SECTION_BY_KEY.get(r["section"])
        color = config.CHART_COLORS.get(r["section"], T["ink_3"])
        icon = sec.icon if sec else ""
        tag = '<span class="tag-sample">Sample</span>' if bool(r["is_sample"]) else ""
        width = int(round(float(r["share"]) * 120))
        disc_td = f'<td class="num">{fmt_disc(r["discount"])}</td>' if show_discount else ""
        rows.append(
            f'<tr><td><span class="dot" style="background:{color}"></span>{icon} <b>{esc(r["section"])}</b>{tag}</td>'
            f'<td class="num">{fmt_n(r["checks"])}</td><td class="num">{fmt_n(r["sales"])}</td>{disc_td}'
            f'<td class="num">{fmt_n(r["aov"])}</td>'
            f'<td class="num"><span class="share-bar" style="width:{width}px;--accent:{color}"></span>{fmt_pct(r["share"])}</td></tr>'
        )
    t_checks, t_sales, t_disc = sections["checks"].sum(), sections["sales"].sum(), sections["discount"].sum()
    disc_tot = f'<td class="num">{fmt_n(t_disc)}</td>' if show_discount else ""
    aov = t_sales / t_checks if t_checks else 0
    rows.append(f'<tr class="grand"><td>All sections</td><td class="num">{fmt_n(t_checks)}</td><td class="num">{fmt_n(t_sales)}</td>'
                f'{disc_tot}<td class="num">{fmt_n(aov)}</td><td class="num">100%</td></tr>')
    st.html(
        f'<div class="card"><div class="card-title">Sales by section<span class="muted">LOTs and event sections · {config.CURRENCY}</span></div>'
        f'<div class="tbl-wrap"><table class="dt"><thead><tr><th>Section</th><th class="num">Checks</th><th class="num">Sales</th>{disc_th}'
        f'<th class="num">AOV</th><th class="num">Share</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>'
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
        st.html('<div class="card-title">Daily sales<span class="muted">stacked by section</span></div>')
        fig = go.Figure()
        for sec_key, color in zip(labels, colors):
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
        _html_legend(labels, colors)


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
                                    "Сумма со скидкой": st.column_config.NumberColumn(format="%d"),
                                    "Сумма скидки": st.column_config.NumberColumn(format="%d")})
        fname = f"cop17_{section_key.replace(' ', '_').replace(',', '')}_{start:%Y%m%d}-{end:%Y%m%d}.csv"
        st.download_button("Download CSV", data=lambda: records.to_csv(index=False).encode("utf-8-sig"),
                           file_name=fname, mime="text/csv", on_click="ignore", key="dl_csv")
