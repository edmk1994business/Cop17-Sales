"""Parser reconciliation tests.  Run:  python -m pytest tests -q   (or: python tests/test_parser.py)

Builds the mock iiko workbook and checks:
  * every daily sheet's parsed totals equal its own "Итого" row,
  * POS Arcus + Банковские карты → Bank Cards, Наличные → Cash, Փոխանցում → Bank Transfers / Invoices,
  * the three period-summary sheets yield the right total, period and (where stated) check count —
    including the iiko-headed "01.10.2026 по 21.10.2026" shape and the "պետական գնումներ" sheet alias,
  * compliments are split out, period totals are counted only when fully covered, discounts omitted at 0.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import data as D  # noqa: E402
from tests.make_sample import main as make_workbook  # noqa: E402


def _build():
    path = os.path.join(tempfile.mkdtemp(), "COP-17-Sales.xlsx")
    expected, periods = make_workbook(path)
    with open(path, "rb") as fh:
        sheets = D.read_workbook(fh.read())
    return sheets, expected, periods


def test_every_daily_sheet_reconciles_with_itogo():
    sheets, expected, _ = _build()
    for name, (checks, sales, discount) in expected.items():
        tidy = D.parse_sheet(sheets[name], name)
        assert int(tidy["checks"].sum()) == checks, name
        assert int(tidy["sales"].sum()) == sales, name
        assert int(tidy["discount"].sum()) == discount, name
        assert not tidy["payment_type"].str.contains("всего|итого", case=False).any(), name
        assert tidy["date"].notna().all(), name


def test_payment_consolidation():
    sheets, expected, _ = _build()
    tidy = D.parse_sheet(sheets["LOT 3"], "LOT 3")
    assert set(tidy["payment_type"]) == {"Bank Cards", "Cash"}
    assert set(tidy["payment_raw"]) == {"POS Arcus", "Банковские карты", "Наличные"}
    totals = D.payment_totals(tidy)
    assert totals["payment_type"].tolist() == ["Bank Cards", "Cash"]
    assert int(totals["sales"].sum()) == expected["LOT 3"][1]
    cards = tidy[tidy["payment_raw"].isin(["POS Arcus", "Банковские карты"])]["sales"].sum()
    assert int(totals.set_index("payment_type").loc["Bank Cards", "sales"]) == int(cards)


def test_column_c_period_sheets():
    sheets, _, periods = _build()
    for name, (checks, total, (start, end)) in periods.items():
        p = D.parse_period_sheet(sheets[name], name)
        assert p is not None, name
        assert int(p.total) == total, name
        assert (p.start, p.end) == (start, end), name
        assert p.checks == checks, name
    side = D.parse_period_sheet(sheets["side events, CBD, Ֆուրշետներ"], "side events, CBD, Ֆուրշետներ")
    assert [e[1] for e in side.entries] == ["CBD reception", "Ֆուրշետ · Pavilion B", "Side event dinner"]
    state = D.parse_period_sheet(sheets["պետական գնումներ"], "State Orders")
    assert {e[1] for e in state.entries} == {"Bank Transfers / Invoices"}
    assert all(e[0] is None for e in state.entries)          # a period range on the line is not a line date


def test_sheet_aliases_and_period_fallback():
    sheets, _, _ = _build()
    ds = D.build_dataset(sheets, "local")
    info = ds.info["State Orders (պետական պատվերներ)"]
    assert info.source == "period" and info.sheet == "պետական գնումներ"
    assert ds.info["Banquet Hall"].source == "period" and ds.info["Banquet Hall"].sheet == "LOT 4"
    assert ds.info["Restaurant Area"].source == "daily" and ds.info["Restaurant Area"].sheet == "LOT 3"
    assert not [k for k, i in ds.info.items() if i.source == "missing"]


def test_payment_mapping_rules():
    cases = {"POS Arcus": "Bank Cards", "Банковские карты": "Bank Cards", "Наличные": "Cash",
             "Փոխանցում": "Bank Transfers / Invoices", "Փոխանցումով": "Bank Transfers / Invoices",
             "Безналичный расчет": "Bank Transfers / Invoices", "Glovo": "Glovo", "без оплаты": "без оплаты"}
    for raw, want in cases.items():
        assert D.map_payment(raw) == want, raw


GENERAL = "General / Global View"


def test_period_totals_counted_only_when_fully_covered():
    sheets, expected, periods = _build()
    ds = D.build_dataset(sheets, "local")
    assert (ds.dmin, ds.dmax) == (date(2026, 10, 1), date(2026, 10, 30))  # widest range across all sheets
    full = D.kpis(D.select(ds, GENERAL, ds.dmin, ds.dmax), D.select_periods(ds, GENERAL, ds.dmin, ds.dmax))
    daily_net = sum(s for _, s, _ in expected.values()) - 81_777  # LOT 10 compliments are excluded
    assert int(full["sales"]) == daily_net + sum(t for _, t, _ in periods.values())
    one_day = date(2026, 10, 22)
    assert D.select_periods(ds, GENERAL, one_day, one_day) == []
    # Banquet Hall (19–30 Oct) and Side Events (20–24 Oct) touch 22 Oct but are not covered → listed as excluded;
    # State Orders (1–21 Oct) does not touch it at all, so it is neither counted nor listed.
    assert {p.section for p in D.excluded_periods(ds, GENERAL, one_day, one_day)} == {"Banquet Hall", "Side Events & Banquets"}
    assert len(D.select_periods(ds, GENERAL, date(2026, 10, 20), date(2026, 10, 24))) == 1  # side events only


def test_compliments_are_split_out():
    sheets, _, _ = _build()
    ds = D.build_dataset(sheets, "local")
    comp = D.select(ds, "Compliments", ds.dmin, ds.dmax)
    general = D.select(ds, GENERAL, ds.dmin, ds.dmax)
    assert comp["is_compliment"].all() and len(comp) > 0
    assert not general["is_compliment"].any()
    assert set(comp["payment_raw"].str.casefold()) == {"без оплаты"}


def test_discount_column_omitted_when_zero():
    sheets, _, _ = _build()
    ds = D.build_dataset(sheets, "local")
    lot3 = D.select(ds, "Restaurant Area", ds.dmin, ds.dmax)
    assert D.kpis(lot3)["has_discount"] is False
    assert "Сумма скидки" not in D.raw_records(lot3).columns
    assert D.kpis(D.select(ds, "Staff Canteen", ds.dmin, ds.dmax))["has_discount"] is True


def test_daily_pivot_columns():
    sheets, _, _ = _build()
    ds = D.build_dataset(sheets, "local")
    df = D.select(ds, GENERAL, ds.dmin, ds.dmax)
    pv = D.daily_pivot(df)
    assert list(pv.columns) == ["date", "Bank Cards", "Cash", "checks", "sales", "discount"]
    assert len(pv) == 4
    assert abs((pv["Bank Cards"] + pv["Cash"] - pv["sales"]).abs().max()) < 1e-6


if __name__ == "__main__":
    for fn in (test_every_daily_sheet_reconciles_with_itogo, test_payment_consolidation, test_column_c_period_sheets,
               test_sheet_aliases_and_period_fallback, test_payment_mapping_rules,
               test_period_totals_counted_only_when_fully_covered, test_compliments_are_split_out,
               test_discount_column_omitted_when_zero, test_daily_pivot_columns):
        fn()
        print("ok ", fn.__name__)
