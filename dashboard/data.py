"""Data pipeline.

1. Download ``COP-17-Sales.xlsx`` from Dropbox (direct link) or fall back to a local copy.
2. Parse every section sheet **by shape**:
   * iiko OLAP *pivot* exports (LOT 3 / 8 / 9 / 10): a few title rows, a header row, dimension
     labels only on the first row of each block (merged cells), ``… всего`` subtotal rows and an
     ``Итого`` grand total → daily rows (date × payment type);
   * "column C" summary sheets (LOT 4, side events, պետական պատվերներ): one total in column C
     plus the date period written on the sheet → a period total.
3. Consolidate payment types (POS Arcus + Банковские карты → Bank Cards, Наличные → Cash).
4. Expose one tidy frame for all daily rows plus the period totals; ``General`` aggregates every
   section and ``Compliments`` is every ``без оплаты`` row.
"""
from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
import streamlit as st

from . import config
from .schema import NUMERIC, TIDY_COLUMNS, empty_tidy

# ----------------------------------------------------------------------------- helpers
_WS = re.compile(r"\s+")
_SUBTOTAL = ("всего", "итого", "total", "ընդամենը", "ընդհանուր")
_NUM_JUNK = re.compile(r"[\s  ֏₽$]")
_DATE_RE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](20\d{2}|\d{2})(?![\d.])")
_DAY_RANGE_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*[-–—]\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})(?![\d.])")  # "19-30.10.2026"
_DM_RANGE_RE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})\s*[-–—]\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})(?![\d.])")  # "19.10-30.10.2026"
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def norm(value) -> str:
    """Casefold + collapse whitespace; '' for blanks and NaN."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return _WS.sub(" ", str(value).replace(" ", " ")).strip().casefold()


def is_blank(value) -> bool:
    return norm(value) == ""


def is_subtotal_label(value) -> bool:
    text = norm(value)
    return bool(text) and any(marker in text for marker in _SUBTOTAL)


def clean_label(value) -> str:
    """Strip whitespace, surrounding brackets and a trailing 'всего'."""
    text = _WS.sub(" ", str(value).replace(" ", " ")).strip()
    text = re.sub(r"\s*(всего|итого)\s*$", "", text, flags=re.IGNORECASE).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return text


def map_payment(label: str) -> str:
    """POS Arcus + Банковские карты → Bank Cards, Наличные → Cash; anything else keeps its label."""
    return config.PAYMENT_MAP.get(norm(label), label)


def parse_num_text(text: str) -> float | None:
    """'12 345,00' → 12345.0 · '3,200,000' → 3200000 · '1.250.000' → 1250000 · '2,5' → 2.5."""
    t = _NUM_JUNK.sub("", str(text))
    if not t or t in ("-", ".", ",") or t.casefold() in ("nan", "none", "nat"):
        return None
    if _DATE_RE.search(t) or _ISO_RE.search(t):
        return None  # "19.10.2026" is a date, not 19 million
    if "," in t and "." in t:
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        t = t.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = t.replace(",", "") if (t.count(",") > 1 or len(tail) == 3) else head + "." + tail
    elif t.count(".") > 1 or (t.count(".") == 1 and len(t.rpartition(".")[2]) == 3):
        t = t.replace(".", "")  # dots as thousands separators
    try:
        return float(t)
    except ValueError:
        return None


def cell_number(value) -> float | None:
    """One cell → float, accepting text numbers; None when it is not a number (dates included)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return None
    return parse_num_text(str(value))


def to_number(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return pd.to_numeric(series.map(cell_number), errors="coerce")


def to_date(series: pd.Series) -> pd.Series:
    """Accept datetimes, Excel serials and 'dd.mm.yyyy' strings; returns datetime.date / NaT."""
    if pd.api.types.is_datetime64_any_dtype(series):
        out = pd.to_datetime(series, errors="coerce")
    else:
        text = series.astype(str).str.strip()
        text = text.str.replace(r"\s*(всего|итого)\s*$", "", regex=True, flags=re.IGNORECASE)
        out = pd.to_datetime(text, dayfirst=True, errors="coerce")
        serial = pd.to_numeric(text, errors="coerce")
        mask = out.isna() & serial.between(20_000, 80_000)
        if mask.any():
            out[mask] = pd.to_datetime(serial[mask], unit="D", origin="1899-12-30")
    return out.dt.date


def cell_dates(value) -> list[date]:
    """All dates mentioned in one cell: a datetime, '22.10.2026', '19-30.10.2026', '19.10-30.10.2026'."""
    return extract_dates(value)[0]


def cell_text(value) -> str:
    """The cell's text with every date removed — what is left is the label."""
    return extract_dates(value)[1]


def extract_dates(value) -> tuple[list[date], str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return [], ""
    if isinstance(value, (datetime, pd.Timestamp)):
        return ([] if pd.isna(value) else [value.date()]), ""
    if isinstance(value, date):
        return [value], ""
    if isinstance(value, (int, float)):
        return [], ""  # a bare number in a summary sheet is an amount, never a date serial
    text = str(value)
    found: list[date] = []

    def _add(y, m, d) -> None:
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass

    # Most specific patterns first; each consumed span is blanked so it is not re-read by the next one.
    def _consume(pattern, handler):
        nonlocal text
        for m in list(pattern.finditer(text)):
            handler(m.groups())
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]

    _consume(_DM_RANGE_RE, lambda g: (_add(g[4], g[1], g[0]), _add(g[4], g[3], g[2])))
    _consume(_DAY_RANGE_RE, lambda g: (_add(g[3], g[2], g[0]), _add(g[3], g[2], g[1])))
    _consume(_DATE_RE, lambda g: _add(int(g[2]) if len(g[2]) == 4 else 2000 + int(g[2]), g[1], g[0]))
    _consume(_ISO_RE, lambda g: _add(g[0], g[1], g[2]))
    rest = _WS.sub(" ", re.sub(r"^[\s\-–—:;,.·՝]+|[\s\-–—:;,.·՝]+$", "", text)).strip()
    return found, rest


def is_compliment(payment_type) -> bool:
    text = norm(payment_type)
    return any(marker in text for marker in config.COMPLIMENT_MARKERS)


# ----------------------------------------------------------------------------- header matching
def classify_header(label) -> str | None:
    """Map an iiko column header to a tidy column by keyword (order matters)."""
    text = norm(label)
    if not text:
        return None
    if "учетный день" in text or "учётный день" in text or text.startswith("дата") or text == "день":
        return "date"
    if "тип оплаты" in text or "вид оплаты" in text or "payment" in text:
        return "payment_type"
    if "со скидкой" in text or "со скидки" in text:
        return "sales"
    if "без скидки" in text or "без скидок" in text:
        return "gross"
    if "скидк" in text or "discount" in text:
        return "discount"
    if ("чек" in text or "заказ" in text or "orders" in text or "checks" in text) and "сумм" not in text:
        return "checks"
    return None


def find_header_row(raw: pd.DataFrame, max_scan: int = 40) -> int | None:
    best, best_hits = None, 0
    for r in range(min(max_scan, len(raw))):
        hits = sum(1 for v in raw.iloc[r].tolist() if classify_header(v))
        if hits > best_hits:
            best, best_hits = r, hits
        if hits >= 3:
            return r
    return best if best_hits >= 3 else None


def looks_like_pivot(raw: pd.DataFrame) -> bool:
    return raw is not None and not raw.empty and find_header_row(raw) is not None


# ----------------------------------------------------------------------------- iiko pivot parser
def parse_sheet(raw: pd.DataFrame, section: str) -> pd.DataFrame:
    """Turn one iiko pivot sheet (read with header=None) into the tidy layout."""
    if raw is None or raw.empty:
        return empty_tidy()
    raw = raw.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)
    raw.columns = range(raw.shape[1])
    hdr = find_header_row(raw)
    if hdr is None:
        return empty_tidy()

    labels = raw.iloc[hdr].tolist()
    roles: dict[int, str] = {}
    for col, label in enumerate(labels):
        role = classify_header(label)
        if role and role not in roles.values():
            roles[col] = role
    metric_cols = [c for c, r in roles.items() if r in NUMERIC]
    if "sales" not in roles.values() or not metric_cols:
        return empty_tidy()
    first_metric = min(metric_cols)

    body = raw.iloc[hdr + 1:].reset_index(drop=True)
    # Dimension columns: everything left of the first metric that carries labels or text.
    dim_cols = []
    for c in range(first_metric):
        has_text = body[c].map(lambda v: not is_blank(v)).any()
        if not is_blank(labels[c]) or has_text:
            dim_cols.append(c)
    if not dim_cols:
        return empty_tidy()
    innermost = dim_cols[-1]

    # 1. Drop subtotal / grand-total rows ("22.10.2026 всего", "LOT 3 всего", "Итого").
    sub_mask = body[dim_cols].apply(lambda r: any(is_subtotal_label(v) for v in r), axis=1)
    body = body[~sub_mask].copy()

    # 2. Forward-fill the merged dimension cells (so days appended at the bottom parse too).
    for c in dim_cols:
        body[c] = body[c].map(lambda v: None if is_blank(v) else v).ffill()

    # 3. Keep detail rows only (innermost dimension present).
    body = body[body[innermost].map(lambda v: not is_blank(v))].copy()
    if body.empty:
        return empty_tidy()

    tidy = pd.DataFrame(index=body.index)
    tidy["section"] = section
    date_col = next((c for c, r in roles.items() if r == "date"), None)
    pay_col = next((c for c, r in roles.items() if r == "payment_type"), None)
    entity_cols = [c for c in dim_cols if c not in (date_col, pay_col)]
    tidy["entity"] = (
        body[entity_cols].apply(lambda r: " · ".join(clean_label(v) for v in r if not is_blank(v)), axis=1)
        if entity_cols else ""
    )
    tidy["date"] = to_date(body[date_col]) if date_col is not None else pd.NaT
    tidy["payment_raw"] = body[pay_col].map(clean_label) if pay_col is not None else "—"
    tidy["payment_type"] = tidy["payment_raw"].map(map_payment)
    for metric in NUMERIC:
        col = next((c for c, r in roles.items() if r == metric), None)
        tidy[metric] = to_number(body[col]).fillna(0.0) if col is not None else 0.0
    if "gross" not in roles.values():
        tidy["gross"] = tidy["sales"] + tidy["discount"]

    # 4. Drop rows without a date and empty transaction rows.
    tidy = tidy[tidy["date"].notna()]
    tidy = tidy[(tidy["checks"] != 0) | (tidy["sales"] != 0)]
    if tidy.empty:
        return empty_tidy()
    tidy["is_compliment"] = tidy["payment_raw"].map(is_compliment)

    keys = ["section", "entity", "date", "payment_type", "payment_raw", "is_compliment"]
    out = tidy.groupby(keys, as_index=False, sort=True)[NUMERIC].sum()
    return out[TIDY_COLUMNS].reset_index(drop=True)


# ----------------------------------------------------------------------------- column-C summary sheets
@dataclass
class PeriodSummary:
    section: str
    start: date
    end: date
    total: float
    checks: int | None = None          # when the sheet states a check count
    entries: list[tuple] = field(default_factory=list)   # (date|None, label, amount) rows found
    period_from_sheet: bool = True     # False when the period had to be taken from the LOT data
    total_label: str = ""

    def covered_by(self, start: date, end: date) -> bool:
        return start <= self.start and self.end <= end

    def overlaps(self, start: date, end: date) -> bool:
        return self.start <= end and start <= self.end


def parse_period_sheet(raw: pd.DataFrame, section: str) -> PeriodSummary | None:
    """A sheet holding one total in column C and its date period somewhere on the sheet."""
    if raw is None or raw.empty or raw.shape[1] < 2:
        return None
    # The totals live in column C; if C holds nothing numeric, fall back to the right-most numeric column.
    numeric_cols = [c for c in range(raw.shape[1]) if raw.iloc[:, c].map(cell_number).notna().any()]
    if not numeric_cols:
        return None
    value_col = 2 if (raw.shape[1] > 2 and 2 in numeric_cols) else numeric_cols[-1]
    col_c = raw.iloc[:, value_col]
    labels = raw.iloc[:, [c for c in range(raw.shape[1]) if c != value_col][:2]]

    # Every row with a number in column C becomes a candidate (label = text in A/B, date if any).
    candidates: list[dict] = []
    for i in range(len(raw)):
        amount = cell_number(col_c.iloc[i])
        if amount is None:
            continue
        a, b = labels.iloc[i, 0], labels.iloc[i, 1]
        parts = [extract_dates(v) for v in (a, b) if not is_blank(v)]
        text = " · ".join(t for _, t in parts if t)
        found = [d for ds, _ in parts for d in ds]
        candidates.append(dict(row=i, amount=amount, label=text, dates=found,
                               is_total=is_subtotal_label(a) or is_subtotal_label(b),
                               is_checks=any(k in norm(text) for k in ("чек", "заказ", "check", "order", "չեկ", "պատվեր")
                                             ) and amount < 100_000))
    if not candidates:
        return None

    checks_rows = [c for c in candidates if c["is_checks"]]
    checks = int(round(checks_rows[0]["amount"])) if checks_rows else None
    money = [c for c in candidates if not c["is_checks"]]
    if not money:
        return None
    totals = [c for c in money if c["is_total"]]
    entries = [c for c in money if not c["is_total"]]
    if totals:
        total, total_label = totals[-1]["amount"], totals[-1]["label"]
    elif len(entries) == 1:
        total, total_label = entries[0]["amount"], entries[0]["label"]
        entries = []
    else:
        biggest = max(entries, key=lambda c: c["amount"])
        rest = sum(c["amount"] for c in entries) - biggest["amount"]
        if abs(biggest["amount"] - rest) <= max(1.0, 0.005 * biggest["amount"]):  # an unlabeled total row
            total, total_label = biggest["amount"], biggest["label"]
            entries = [c for c in entries if c is not biggest]
        else:
            total, total_label = float(sum(c["amount"] for c in entries)), "sum of rows"

    # The period: every date written anywhere on the sheet.
    all_dates = [d for v in raw.to_numpy().ravel() for d in cell_dates(v)]
    if all_dates:
        start, end, from_sheet = min(all_dates), max(all_dates), True
    else:
        start, end, from_sheet = config.EVENT_START, config.EVENT_END, False
    rows = [((c["dates"][0] if c["dates"] else None), clean_label(c["label"]) or "—", c["amount"]) for c in entries]
    return PeriodSummary(section, start, end, float(total), checks, rows, from_sheet, clean_label(total_label))


# ----------------------------------------------------------------------------- workbook loading
@dataclass
class SectionInfo:
    key: str
    source: str              # "daily" | "period" | "missing"
    sheet: str | None = None
    rows: int = 0
    sales: float = 0.0
    note: str = ""


@dataclass
class Dataset:
    df: pd.DataFrame
    periods: dict[str, PeriodSummary] = field(default_factory=dict)
    info: dict[str, SectionInfo] = field(default_factory=dict)
    dmin: date | None = None
    dmax: date | None = None
    loaded_at: float = 0.0
    origin: str = ""         # "dropbox" | "local" | "none"
    error: str | None = None
    workbook_sheets: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.df.empty and not self.periods

    @property
    def daily_count(self) -> int:
        return sum(1 for i in self.info.values() if i.source == "daily")

    @property
    def period_count(self) -> int:
        return sum(1 for i in self.info.values() if i.source == "period")


def _sheet_key(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", norm(name))


def find_sheet(sheets: dict[str, pd.DataFrame], wanted: str) -> str | None:
    want = _sheet_key(wanted)
    for name in sheets:
        if _sheet_key(name) == want:
            return name
    for name in sheets:  # "LOT 3 (final)" still matches "LOT 3", but "LOT 10" never matches "LOT 1"
        key = _sheet_key(name)
        if key.startswith(want) and not key[len(want):len(want) + 1].isdigit():
            return name
    return None


def _download(url: str, timeout: int = 40) -> bytes:
    import requests

    url = re.sub(r"([?&])dl=0", r"\1dl=1", url)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "cop17-dashboard/1.0"})
    resp.raise_for_status()
    body = resp.content
    if not body.startswith(b"PK"):
        raise ValueError("The link did not return an .xlsx file (got HTML). Check the Dropbox share link / dl=1.")
    return body


def read_workbook(blob: bytes) -> dict[str, pd.DataFrame]:
    bio = io.BytesIO(blob)
    try:
        return pd.read_excel(bio, sheet_name=None, header=None, engine="calamine")
    except Exception:
        bio.seek(0)
        return pd.read_excel(bio, sheet_name=None, header=None, engine="openpyxl")


def build_dataset(sheets: dict[str, pd.DataFrame], origin: str, error: str | None = None) -> Dataset:
    frames: list[pd.DataFrame] = []
    periods: dict[str, PeriodSummary] = {}
    info: dict[str, SectionInfo] = {}

    for section in config.SALES_SECTIONS:
        name = find_sheet(sheets, section.sheet or section.key)
        if name is None:
            info[section.key] = SectionInfo(section.key, "missing", None, 0, 0.0, "Sheet not found in the workbook.")
            continue
        raw = sheets[name]
        if looks_like_pivot(raw):
            tidy = parse_sheet(raw, section.key)
            if tidy.empty:
                info[section.key] = SectionInfo(section.key, "missing", name, 0, 0.0,
                                                "Sheet found but no sales rows could be parsed.")
                continue
            frames.append(tidy)
            info[section.key] = SectionInfo(section.key, "daily", name, len(tidy),
                                            float(tidy.loc[~tidy["is_compliment"], "sales"].sum()))
        else:
            summary = parse_period_sheet(raw, section.key)
            if summary is None:
                info[section.key] = SectionInfo(section.key, "missing", name, 0, 0.0,
                                                "Sheet found but no total was found in column C.")
                continue
            periods[section.key] = summary
            info[section.key] = SectionInfo(section.key, "period", name, len(summary.entries), summary.total)

    df = pd.concat(frames, ignore_index=True) if frames else empty_tidy()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values(["date", "section", "payment_type"]).reset_index(drop=True)

    # Full period = earliest .. latest recorded date across every sheet (daily rows and period sheets).
    starts = ([df["date"].min()] if not df.empty else []) + [p.start for p in periods.values() if p.period_from_sheet]
    ends = ([df["date"].max()] if not df.empty else []) + [p.end for p in periods.values() if p.period_from_sheet]
    dmin = min(starts) if starts else config.EVENT_START
    dmax = max(ends) if ends else config.EVENT_END
    for p in periods.values():  # a sheet without any date written on it spans the data range
        if not p.period_from_sheet:
            p.start, p.end = dmin, dmax
    return Dataset(df=df, periods=periods, info=info, dmin=dmin, dmax=dmax, loaded_at=time.time(),
                   origin=origin, error=error, workbook_sheets=tuple(sheets.keys()))


@st.cache_data(ttl=config.CACHE_TTL_SECONDS, show_spinner=False)
def load_dataset(source_url: str, local_path: str) -> Dataset:
    sheets: dict[str, pd.DataFrame] = {}
    origin, error = "none", None
    if source_url:
        try:
            sheets = read_workbook(_download(source_url))
            origin = "dropbox"
        except Exception as exc:  # noqa: BLE001 — surfaced in the UI
            reason = type(exc).__name__ if len(str(exc)) > 160 else str(exc)
            error = f"Dropbox download failed ({reason})."
    if not sheets and local_path:
        try:
            with open(local_path, "rb") as fh:
                sheets = read_workbook(fh.read())
            origin = "local"
            error = None if error is None else error + f" — using local copy {local_path}."
        except FileNotFoundError:
            pass
        except Exception as exc:  # noqa: BLE001
            error = (error + " " if error else "") + f"Local file failed: {exc}"
    return build_dataset(sheets, origin, error)


# ----------------------------------------------------------------------------- selection & metrics
def select(ds: Dataset, section_key: str, start: date, end: date) -> pd.DataFrame:
    """Daily rows for one tab inside [start, end]. General = all sections minus compliments."""
    df = ds.df
    if df.empty:
        return df
    section = config.SECTION_BY_KEY[section_key]
    mask = (df["date"] >= start) & (df["date"] <= end)
    if section.kind == "compliments":
        mask &= df["is_compliment"]
    elif section.kind == "global":
        mask &= ~df["is_compliment"]
    else:
        mask &= (df["section"] == section_key) & ~df["is_compliment"]
    return df.loc[mask].copy()


def select_periods(ds: Dataset, section_key: str, start: date, end: date) -> list[PeriodSummary]:
    """Period totals that belong to the tab and are fully covered by the selected range.

    A period total is one number for its whole period, so it is counted only when the selected
    range contains that period (always true for "Full Event Period"); it is never pro-rated."""
    section = config.SECTION_BY_KEY[section_key]
    if section.kind == "global":
        pool = list(ds.periods.values())
    elif section.kind == "sheet":
        pool = [ds.periods[section_key]] if section_key in ds.periods else []
    else:
        pool = []
    return [p for p in pool if p.covered_by(start, end)]


def excluded_periods(ds: Dataset, section_key: str, start: date, end: date) -> list[PeriodSummary]:
    """Period totals that touch the range but are not fully covered (so they are left out)."""
    section = config.SECTION_BY_KEY[section_key]
    if section.kind == "global":
        pool = list(ds.periods.values())
    elif section.kind == "sheet":
        pool = [ds.periods[section_key]] if section_key in ds.periods else []
    else:
        pool = []
    return [p for p in pool if p.overlaps(start, end) and not p.covered_by(start, end)]


def kpis(df: pd.DataFrame, periods: list[PeriodSummary] | None = None) -> dict:
    periods = periods or []
    d_sales = float(df["sales"].sum()) if not df.empty else 0.0
    d_checks = int(round(df["checks"].sum())) if not df.empty else 0
    discount = float(df["discount"].sum()) if not df.empty else 0.0
    gross = float(df["gross"].sum()) if not df.empty else 0.0
    p_sales = sum(p.total for p in periods)
    p_checks = sum(p.checks for p in periods if p.checks)
    aov_sales = d_sales + sum(p.total for p in periods if p.checks)   # only sales whose checks are known
    checks = d_checks + p_checks
    unknown_checks = any(p.checks is None for p in periods)
    days = int(df["date"].nunique()) if not df.empty else 0
    return dict(
        sales=d_sales + p_sales,
        daily_sales=d_sales,
        period_sales=p_sales,
        checks=checks,
        checks_partial=unknown_checks and bool(periods),
        aov=(aov_sales / checks) if checks else 0.0,
        discount=discount,
        gross=gross + p_sales,
        days=days,
        has_discount=discount > 0,
        has_periods=bool(periods),
    )


def payment_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["payment_type", "checks", "sales", "discount", "share"])
    g = df.groupby("payment_type", as_index=False)[["checks", "sales", "discount"]].sum()
    g["order"] = g["payment_type"].map(lambda p: config.PAYMENT_ORDER.index(p) if p in config.PAYMENT_ORDER else 99)
    g = g.sort_values(["order", "sales"], ascending=[True, False]).drop(columns="order").reset_index(drop=True)
    total = g["sales"].sum()
    g["share"] = g["sales"] / total if total else 0.0
    return g


def payment_columns(df: pd.DataFrame) -> list[str]:
    """Bank Cards, Cash, then any other payment type present — by sales, descending."""
    if df.empty:
        return []
    present = payment_totals(df)["payment_type"].tolist()
    return [p for p in config.PAYMENT_ORDER if p in present] + [p for p in present if p not in config.PAYMENT_ORDER]


def daily_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """One row per day: sales per payment column, total checks, total sales, discount."""
    cols = payment_columns(df)
    if df.empty:
        return pd.DataFrame(columns=["date", *cols, "checks", "sales", "discount"])
    pv = df.pivot_table(index="date", columns="payment_type", values="sales", aggfunc="sum", fill_value=0.0)
    pv = pv.reindex(columns=cols, fill_value=0.0)
    tot = df.groupby("date")[["checks", "sales", "discount"]].sum()
    out = pv.join(tot).reset_index().sort_values("date").reset_index(drop=True)
    return out


def section_totals(df: pd.DataFrame, periods: list[PeriodSummary] | None = None) -> pd.DataFrame:
    rows = []
    if not df.empty:
        g = df.groupby("section", as_index=False).agg(checks=("checks", "sum"), sales=("sales", "sum"),
                                                        discount=("discount", "sum"))
        for _, r in g.iterrows():
            rows.append(dict(section=r["section"], checks=int(r["checks"]), sales=float(r["sales"]),
                             discount=float(r["discount"]), kind="daily", period=None))
    for p in periods or []:
        rows.append(dict(section=p.section, checks=p.checks, sales=p.total, discount=0.0, kind="period",
                         period=(p.start, p.end)))
    if not rows:
        return pd.DataFrame(columns=["section", "checks", "sales", "discount", "kind", "period", "aov", "share"])
    g = pd.DataFrame(rows)
    order = {s.key: i for i, s in enumerate(config.SECTIONS)}
    g["order"] = g["section"].map(order).fillna(99)
    g = g.sort_values("order").drop(columns="order").reset_index(drop=True)
    g["aov"] = g.apply(lambda r: (r["sales"] / r["checks"]) if r["checks"] else None, axis=1)
    total = g["sales"].sum()
    g["share"] = g["sales"] / total if total else 0.0
    return g


def daily_by_section(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "section", "sales"])
    return df.groupby(["date", "section"], as_index=False)["sales"].sum()


def raw_records(df: pd.DataFrame) -> pd.DataFrame:
    """Underlying rows for the table/CSV download with human column names."""
    cols = ["date", "section", "entity", "payment_type", "payment_raw", "checks", "sales", "discount"]
    out = df[cols].copy()
    if (out["entity"] == "").all():
        out = out.drop(columns="entity")
    if out["discount"].sum() == 0:
        out = out.drop(columns="discount")
    rename = {"date": "Учетный день", "section": "Section", "entity": "Entity", "payment_type": "Payment",
              "payment_raw": "Тип оплаты (iiko)", "checks": "Чеков", "sales": "Сумма со скидкой",
              "discount": "Сумма скидки"}
    return out.rename(columns=rename).sort_values(["Учетный день", "Section"]).reset_index(drop=True)
