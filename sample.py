"""Deterministic, realistic sample sales for sections that have no sheet in the workbook yet.

Sample rows are flagged ``is_sample=True`` and the UI shows a "Sample data" badge on them.
The generator is seeded per section, so the numbers do not change between reruns.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import SAMPLE_PROFILES
from .schema import TIDY_COLUMNS, empty_tidy

COMPLIMENT_LABEL = "без оплаты"


def generate_sample(section_key: str, start: date, end: date) -> pd.DataFrame:
    """Build a tidy frame for ``section_key`` covering ``start``..``end`` (inclusive)."""
    profile = SAMPLE_PROFILES.get(section_key)
    if profile is None or start is None or end is None or end < start:
        return empty_tidy()

    rng = np.random.default_rng(profile["seed"])
    days = pd.date_range(start, end, freq="D")
    labels = list(profile["payments"].keys())
    weights = np.array(list(profile["payments"].values()), dtype=float)
    weights = weights / weights.sum()
    c_lo, c_hi = profile["checks"]
    a_lo, a_hi = profile["aov"]
    k_lo, k_hi = profile["compliments"]
    disc_share = float(profile.get("discount_share", 0.0))

    rows: list[dict] = []
    for ts in days:
        if rng.random() > profile["active_days"]:
            continue
        day = ts.date()
        # Conference traffic ramps up in the first days and softens at the end.
        pos = (ts - days[0]).days / max(len(days) - 1, 1)
        curve = 0.85 + 0.35 * np.sin(np.pi * min(max(pos, 0.0), 1.0))
        total_checks = max(int(round(rng.integers(c_lo, c_hi + 1) * curve)), 1)
        aov = rng.uniform(a_lo, a_hi)
        counts = rng.multinomial(total_checks, weights)
        for label, n in zip(labels, counts):
            if n <= 0:
                continue
            sales = _round10(n * aov * rng.uniform(0.92, 1.08))
            discount = _round10(sales * disc_share * rng.uniform(0.5, 1.5)) if disc_share else 0
            rows.append(_row(section_key, day, label, int(n), sales, discount, False))
        n_comp = int(rng.integers(k_lo, k_hi + 1)) if k_hi > 0 else 0
        if n_comp > 0:
            sales = _round10(n_comp * aov * rng.uniform(0.6, 0.9))
            rows.append(_row(section_key, day, COMPLIMENT_LABEL, n_comp, sales, 0, True))

    if not rows:
        return empty_tidy()
    df = pd.DataFrame(rows, columns=TIDY_COLUMNS)
    return df


def _round10(x: float) -> int:
    return int(round(x / 10.0) * 10)


def _row(section: str, day: date, payment: str, checks: int, sales: int, discount: int,
         is_compliment: bool) -> dict:
    return dict(
        section=section,
        entity="",
        date=day,
        payment_type=payment,
        checks=checks,
        sales=float(sales),
        discount=float(discount),
        gross=float(sales + discount),
        is_compliment=is_compliment,
        is_sample=True,
    )
