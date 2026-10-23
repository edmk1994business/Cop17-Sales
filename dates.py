"""Date presets and the single date state shared by the header controls.

State keys (st.session_state):
    preset        – one of config.PRESETS; defaults to "Full Event Period"
    custom_start  – date, only used by "Custom Date Range"
    custom_end    – date
"""
from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from . import config


def today_local() -> date:
    from datetime import datetime

    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def init_state(dmin: date, dmax: date) -> None:
    """Default = the whole available range (earliest .. latest date in the data)."""
    st.session_state.setdefault("preset", config.PRESET_FULL)
    st.session_state.setdefault("custom_start", dmin)
    st.session_state.setdefault("custom_end", dmax)
    # Clamp a stale custom range (e.g. after a refresh that added new days).
    if st.session_state["custom_start"] > st.session_state["custom_end"]:
        st.session_state["custom_start"], st.session_state["custom_end"] = dmin, dmax


def resolve(preset: str, dmin: date, dmax: date, today: date | None = None) -> tuple[date, date]:
    """Translate a preset into an inclusive (start, end) pair."""
    today = today or today_local()
    if preset == config.PRESET_TODAY:
        return today, today
    if preset == config.PRESET_YESTERDAY:
        y = today - timedelta(days=1)
        return y, y
    if preset == config.PRESET_WEEK:
        monday = today - timedelta(days=today.weekday())
        return monday, today
    if preset == config.PRESET_CUSTOM:
        start = st.session_state.get("custom_start", dmin)
        end = st.session_state.get("custom_end", dmax)
        if start > end:
            start, end = end, start
        return start, end
    return dmin, dmax  # Full Event Period


def set_full_period() -> None:
    st.session_state["preset"] = config.PRESET_FULL


def label(start: date, end: date) -> str:
    """'22 Oct 2026', '19–22 Oct 2026', '28 Oct – 2 Nov 2026' (portable, no %-d)."""
    def dmy(d: date) -> str:
        return f"{d.day} {d.strftime('%b %Y')}"

    def dm(d: date) -> str:
        return f"{d.day} {d.strftime('%b')}"

    if start == end:
        return dmy(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{dmy(end)}"
    if start.year == end.year:
        return f"{dm(start)} – {dmy(end)}"
    return f"{dmy(start)} – {dmy(end)}"
