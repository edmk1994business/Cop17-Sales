"""Parser reconciliation test.  Run:  python -m pytest tests -q   (or: python tests/test_parser.py)

Builds the mock iiko workbook and checks every sheet's parsed totals equal its own "Итого" row.
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import data as D  # noqa: E402
from tests.make_sample import main as make_workbook  # noqa: E402


def _build():
    path = os.path.join(tempfile.mkdtemp(), "COP-17-Sales.xlsx")
    expected = make_workbook(path)
    with open(path, "rb") as fh:
        sheets = D.read_workbook(fh.read())
    return sheets, expected


def test_every_sheet_reconciles_with_itogo():
    sheets, expected = _build()
    for name, (checks, sales, discount) in expected.items():
        tidy = D.parse_sheet(sheets[name], name)
        assert int(tidy["checks"].sum()) == checks, name
        assert int(tidy["sales"].sum()) == sales, name
        assert int(tidy["discount"].sum()) == discount, name
        assert not tidy["payment_type"].str.contains("всего|итого", case=False).any(), name
        assert tidy["date"].notna().all(), name


def test_compliments_are_split_out():
    sheets, _ = _build()
    ds = D.build_dataset(sheets, "local")
    comp = D.select(ds, "Compliments", ds.dmin, ds.dmax)
    general = D.select(ds, "General", ds.dmin, ds.dmax)
    assert comp["is_compliment"].all() and len(comp) > 0
    assert not general["is_compliment"].any()
    assert set(comp["payment_type"].str.casefold()) == {"без оплаты"}


def test_sample_sections_only_fill_missing_sheets():
    sheets, _ = _build()
    ds = D.build_dataset(sheets, "local")
    assert ds.info["LOT 3"].source == "live"
    assert ds.info["LOT 4"].source == "sample"
    sample = ds.df[ds.df["section"] == "LOT 4"]
    assert sample["is_sample"].all()
    assert sample["date"].min() >= ds.dmin and sample["date"].max() <= ds.dmax


def test_discount_column_omitted_when_zero():
    sheets, _ = _build()
    ds = D.build_dataset(sheets, "local")
    lot3 = D.select(ds, "LOT 3", ds.dmin, ds.dmax)
    assert D.kpis(lot3)["has_discount"] is False
    assert "Сумма скидки" not in D.raw_records(lot3).columns
    lot10 = D.select(ds, "LOT 10", ds.dmin, ds.dmax)
    assert D.kpis(lot10)["has_discount"] is True


if __name__ == "__main__":
    for fn in (test_every_sheet_reconciles_with_itogo, test_compliments_are_split_out,
               test_sample_sections_only_fill_missing_sheets, test_discount_column_omitted_when_zero):
        fn()
        print("ok ", fn.__name__)
