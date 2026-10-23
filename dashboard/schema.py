"""The tidy row layout shared by the parser, the sample generator and the UI."""
from __future__ import annotations

import pandas as pd

TIDY_COLUMNS = [
    "section",        # tab / sheet the row belongs to
    "entity",         # optional outer dimension in the pivot (e.g. trading unit); "" if none
    "date",           # datetime.date
    "payment_type",   # consolidated label: "Bank Cards", "Cash", "без оплаты", or the original
    "payment_raw",    # label as exported by iiko, e.g. "POS Arcus"
    "checks",         # Чеков
    "sales",          # Сумма со скидкой (֏)
    "discount",       # Сумма скидки (֏) — 0 when the sheet has no such column
    "gross",          # Сумма без скидки (֏) = sales + discount when the sheet has no such column
    "is_compliment",  # payment type is "без оплаты"
]

NUMERIC = ["checks", "sales", "discount", "gross"]


def empty_tidy() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype=object) for c in TIDY_COLUMNS})
    for c in NUMERIC:
        df[c] = df[c].astype(float)
    df["is_compliment"] = df["is_compliment"].astype(bool)
    return df
