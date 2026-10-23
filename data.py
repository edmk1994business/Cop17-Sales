"""Data pipeline.

1. Download ``COP-17-Sales.xlsx`` from Dropbox (direct link) or fall back to a local copy.
2. Parse every live LOT sheet. The sheets are iiko OLAP *pivot* exports: a few title rows,
   a header row, dimension labels that appear only on the first row of each block
   (merged cells), ``… всего`` subtotal rows after every block and an ``Итого`` grand total.
3. Generate sample data for the sections that have no sheet yet (LOT 4, side events,
   state orders) over the same date range as the live data.
4. Expose one tidy frame for all sections; ``General`` is the aggregate of every
   sales section and ``Compliments`` is every ``без оплаты`` row.
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
from .sample import generate_sample
from .schema import NUMERIC, TIDY_COLUMNS, empty_tidy

# ----------------------------------------------------------------------------- helpers
_WS = re.compile(r"\s+")
_SUBTOTAL = ("всего", "итого", "total")
_NUM_JUNK = re.compile(r"[\s  ֏₽$]")


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


def to_number(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    cleaned = (
        series.astype(str)
        .str.replace(_NUM_JUNK, "", regex=True)
        .str.replace(",", ".", regex=False)
        .replace({"": None, "nan": None, "None": None, "-": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


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
    return best if best_hits >= 2 else None


# ----------------------------------------------------------------------------- the parser
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

    # 2. Forward-fill the merged dimension cells.
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
    tidy["payment_type"] = body[pay_col].map(clean_label) if pay_col is not None else "—"
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
    tidy["is_compliment"] = tidy["payment_type"].map(is_compliment)
    tidy["is_sample"] = False

    keys = ["section", "entity", "date", "payment_type", "is_compliment", "is_sample"]
    out = tidy.groupby(keys, as_index=False, sort=True)[NUMERIC].sum()
    return out[TIDY_COLUMNS].reset_index(drop=True)


# ----------------------------------------------------------------------------- workbook loading
@dataclass
class SectionInfo:
    key: str
    source: str              # "live" | "sample" | "missing"
    sheet: str | None = None
    rows: int = 0
    sales: float = 0.0
    note: str = ""


@dataclass
class Dataset:
    df: pd.DataFrame
    info: dict[str, SectionInfo] = field(default_factory=dict)
    dmin: date | None = None
    dmax: date | None = None
    loaded_at: float = 0.0
    origin: str = ""         # "dropbox" | "local" | "none"
    error: str | None = None
    workbook_sheets: tuple[str, ...] = ()

    @property
    def live_count(self) -> int:
        return sum(1 for i in self.info.values() if i.source == "live")

    @property
    def sample_count(self) -> int:
        return sum(1 for i in self.info.values() if i.source == "sample")


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
    info: dict[str, SectionInfo] = {}

    # Live sheets first (any section may be live if its sheet exists in the workbook).
    for section in config.SALES_SECTIONS:
        name = find_sheet(sheets, section.sheet or section.key)
        if name is None:
            continue
        tidy = parse_sheet(sheets[name], section.key)
        if tidy.empty:
            info[section.key] = SectionInfo(section.key, "missing", name, 0, 0.0,
                                            "Sheet found but no sales rows could be parsed.")
            continue
        frames.append(tidy)
        info[section.key] = SectionInfo(section.key, "live", name, len(tidy),
                                        float(tidy.loc[~tidy["is_compliment"], "sales"].sum()))

    live = pd.concat(frames, ignore_index=True) if frames else empty_tidy()
    if not live.empty:
        dmin, dmax = live["date"].min(), live["date"].max()
    else:
        dmin, dmax = config.EVENT_START, config.EVENT_END

    # Sample sections fill in only where no sheet exists.
    for section in config.SALES_SECTIONS:
        if section.key in info:
            continue
        if section.kind == "sample":
            sample = generate_sample(section.key, dmin, dmax)
            frames.append(sample)
            info[section.key] = SectionInfo(section.key, "sample", None, len(sample),
                                            float(sample.loc[~sample["is_compliment"], "sales"].sum()),
                                            "No sheet in the workbook yet — showing generated sample data.")
        else:
            info[section.key] = SectionInfo(section.key, "missing", None, 0, 0.0,
                                            "Sheet not found in the workbook.")

    df = pd.concat(frames, ignore_index=True) if frames else empty_tidy()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values(["date", "section", "payment_type"]).reset_index(drop=True)
    return Dataset(df=df, info=info, dmin=dmin, dmax=dmax, loaded_at=time.time(), origin=origin,
                   error=error, workbook_sheets=tuple(sheets.keys()))


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
    """Rows for one tab inside [start, end]. General = all sales sections minus compliments."""
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


def kpis(df: pd.DataFrame) -> dict:
    sales = float(df["sales"].sum()) if not df.empty else 0.0
    checks = int(round(df["checks"].sum())) if not df.empty else 0
    discount = float(df["discount"].sum()) if not df.empty else 0.0
    gross = float(df["gross"].sum()) if not df.empty else 0.0
    days = int(df["date"].nunique()) if not df.empty else 0
    return dict(
        sales=sales,
        checks=checks,
        aov=(sales / checks) if checks else 0.0,
        discount=discount,
        gross=gross,
        days=days,
        has_discount=discount > 0,
        is_sample=bool(df["is_sample"].all()) if not df.empty else False,
        has_sample=bool(df["is_sample"].any()) if not df.empty else False,
    )


def payment_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["payment_type", "checks", "sales", "discount", "share"])
    g = df.groupby("payment_type", as_index=False)[["checks", "sales", "discount"]].sum()
    g = g.sort_values("sales", ascending=False).reset_index(drop=True)
    total = g["sales"].sum()
    g["share"] = g["sales"] / total if total else 0.0
    return g


def daily_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Date × payment type rows, sorted by date then sales desc."""
    if df.empty:
        return pd.DataFrame(columns=["date", "payment_type", "checks", "sales", "discount"])
    g = df.groupby(["date", "payment_type"], as_index=False)[["checks", "sales", "discount"]].sum()
    return g.sort_values(["date", "sales"], ascending=[True, False]).reset_index(drop=True)


def section_totals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["section", "checks", "sales", "discount", "aov", "share", "is_sample"])
    g = df.groupby("section", as_index=False).agg(
        checks=("checks", "sum"), sales=("sales", "sum"), discount=("discount", "sum"),
        is_sample=("is_sample", "all"),
    )
    order = {s.key: i for i, s in enumerate(config.SECTIONS)}
    g["order"] = g["section"].map(order).fillna(99)
    g = g.sort_values("order").drop(columns="order").reset_index(drop=True)
    g["aov"] = g.apply(lambda r: r["sales"] / r["checks"] if r["checks"] else 0.0, axis=1)
    total = g["sales"].sum()
    g["share"] = g["sales"] / total if total else 0.0
    return g


def daily_by_section(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", "section", "sales"])
    return df.groupby(["date", "section"], as_index=False)["sales"].sum()


def raw_records(df: pd.DataFrame) -> pd.DataFrame:
    """Underlying rows for the table/CSV download with human column names."""
    cols = ["date", "section", "entity", "payment_type", "checks", "sales", "discount", "is_sample"]
    out = df[cols].copy()
    if (out["entity"] == "").all():
        out = out.drop(columns="entity")
    if out["discount"].sum() == 0:
        out = out.drop(columns="discount")
    if not out["is_sample"].any():
        out = out.drop(columns="is_sample")
    rename = {"date": "Учетный день", "section": "Section", "entity": "Entity", "payment_type": "Тип оплаты",
              "checks": "Чеков", "sales": "Сумма со скидкой", "discount": "Сумма скидки", "is_sample": "Sample"}
    return out.rename(columns=rename).sort_values(["Учетный день", "Section"]).reset_index(drop=True)


def as_datetime(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)
