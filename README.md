# COP17 2026 Armenia — Executive Sales Console

Streamlit dashboard for the COP17 catering operation, driven by one multi-sheet iiko export
(`COP-17-Sales.xlsx` in Dropbox).

```
cop17-dashboard/
├─ app.py                      # entry point (Streamlit Cloud main file)
├─ dashboard/
│  ├─ config.py                # sections, Dropbox link, presets, palette, sample profiles
│  ├─ data.py                  # download → iiko pivot parser → sample fill-in → Global → KPIs
│  ├─ sample.py                # seeded sample generator (LOT 4, side events, state orders)
│  ├─ dates.py                 # Full Event Period (default) / Today / Yesterday / This Week / Custom
│  ├─ schema.py                # the tidy row layout
│  └─ ui.py                    # theme CSS, tab bar, KPI cards, tables, charts
├─ assets/cop17.jpg            # header logo
├─ data/                       # optional local copy of the workbook (fallback)
├─ tests/make_sample.py        # writes a mock iiko workbook (4 title rows, "всего" rows, Итого)
├─ tests/test_parser.py        # reconciles parsed totals with each sheet's Итого
├─ .streamlit/config.toml      # theme + server flags
├─ .streamlit/secrets.toml.example
└─ requirements.txt
```

## Deploy on Streamlit Cloud

1. Push this folder to a GitHub repo.
2. share.streamlit.io → **New app** → repo / branch / main file `app.py`.
3. **Advanced settings → Secrets** (optional — the default link is already in `config.py`):
   ```toml
   SOURCE_URL = "https://www.dropbox.com/scl/fi/…/COP-17-Sales.xlsx?rlkey=…&dl=1"
   ```
   The link must end in `dl=1`. The app caches the workbook for 5 minutes; **↻ Refresh data** or
   opening `…/?refresh=1` (what the RPA calls after an export) clears it.

Run locally: `pip install -r requirements.txt && streamlit run app.py`.
Without internet, drop a copy at `data/COP-17-Sales.xlsx` (or set `LOCAL_PATH`). A mock workbook
for development: `python tests/make_sample.py`.

## How the workbook is read

* Sheets are matched by name, tolerant of spacing/case (`LOT 3`, `Lot3`, `LOT 3 (final)`).
* Each sheet is an iiko OLAP pivot: title rows, a header row (found by keywords — the column
  order does not matter), dimension labels only on the first row of each block, `… всего`
  subtotals and `Итого`. The parser drops subtotal rows, forward-fills the merged dimensions,
  keeps detail rows only, then re-aggregates by date × payment type.
* Columns matched by keyword: `Учетный день`, `Тип оплаты`, `Чеков`/`Заказов`,
  `Сумма со скидкой` (sales), `Сумма скидки` (discount), `Сумма без скидки` (gross, optional).
  Any extra text column left of the numbers (e.g. a trading-unit column) is treated as an
  outer dimension and forward-filled too.
* `без оплаты` rows feed only the **Compliments** tab; every other tab excludes them.
* **LOT 4**, **side events, CBD, Ֆուրշետներ** and **պետական պատվերներ** are generated sample
  data **only while the workbook has no sheet of that name** — add the sheet and it is used
  automatically. Sample sections carry a *Sample* badge. Ranges live in `config.SAMPLE_PROFILES`.
* **General** = every sales section combined (compliments excluded).
* `Сумма скидки` is shown (KPI card and table column) only when the period's total discount > 0.

## Metrics

* Total Sales = Σ `Сумма со скидкой`; Checks = Σ `Чеков`; AOV = Sales ÷ Checks;
  Total Discounts = Σ `Сумма скидки`.
* Default period = earliest … latest date in the workbook.

## Tests

```
python tests/test_parser.py        # or: python -m pytest tests -q
```
