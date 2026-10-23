"""The tidy row layout shared by the parser, the sample generator and the UI."""
from __future__ import annotations

import pandas as pd

TIDY_COLUMNS = [
    "section",        # tab / sheet the row belongs to
    "entity",         # optional outer dimension in the pivot (e.g. trading unit); "" if none
    "date",           # datetime.date
    "payment_type",   # cleaned label, e.g. "POS Arcus", "Наличные", "без оплаты"
    "checks",         # Чеков
    "sales",          # Сумма со скидкой (֏)
    "discount",       # Сумма скидки (֏) — 0 when the sheet has no such column
    "gross",          # Сумма без скидки (֏) = sales + discount when the sheet has no such column
    "is_compliment",  # payment type is "без оплаты"
    "is_sample",      # generated, not from the workbook
]

NUMERIC = ["checks", "sales", "discount", "gross"]


def empty_tidy() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype=object) for c in TIDY_COLUMNS})
    for c in NUMERIC:
        df[c] = df[c].astype(float)
    df["is_compliment"] = df["is_compliment"].astype(bool)
    df["is_sample"] = df["is_sample"].astype(bool)
    return df
