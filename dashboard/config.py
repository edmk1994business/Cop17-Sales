"""Static configuration: sections, data sources, presets and the brand palette."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

APP_TITLE = "COP17 Sales Console"
APP_SUBTITLE = "UN Biodiversity Conference · Yerevan, Armenia · 19–30 October 2026"
TIMEZONE = "Asia/Yerevan"
CURRENCY = "֏"

# Official event window — used only as a fallback when the workbook has no dates yet.
EVENT_START = date(2026, 10, 19)
EVENT_END = date(2026, 10, 30)

# ---------------------------------------------------------------- data sources
# Dropbox share link; dl=0 is rewritten to dl=1 (direct download) at load time.
# Override with SOURCE_URL in .streamlit/secrets.toml.
DEFAULT_SOURCE_URL = (
    "https://www.dropbox.com/scl/fi/0qn6dhg9a166d13nt95ec/COP-17-Sales.xlsx"
    "?rlkey=owkahbr1fyaht9jb3z5qfjl0u&dl=0"
)
LOCAL_FALLBACK = "data/COP-17-Sales.xlsx"
CACHE_TTL_SECONDS = 300


# ---------------------------------------------------------------- sections
@dataclass(frozen=True)
class Section:
    key: str                     # clean dashboard name (tab label, charts, tables)
    icon: str
    kind: str                    # "global" | "sheet" | "compliments"
    color: str                   # accent used on the tab, the KPI rail and the cards
    sheets: tuple[str, ...] = () # workbook sheet name(s) to look for, in order of preference

    @property
    def label(self) -> str:
        return f"{self.icon} {self.key}"


SECTIONS: tuple[Section, ...] = (
    Section("General / Global View", "🌐", "global", "#2E7D4F"),
    Section("Restaurant Area", "🏪", "sheet", "#2E7D4F", sheets=("LOT 3",)),
    Section("Food Trucks", "🚛", "sheet", "#2F6BB5", sheets=("LOT 8",)),
    Section("Coffee, Grab & Go", "☕", "sheet", "#BC860C", sheets=("LOT 9",)),
    Section("Staff Canteen", "🍽️", "sheet", "#8A4FC7", sheets=("LOT 10",)),
    Section("Banquet Hall", "🏛️", "sheet", "#D04A3B", sheets=("LOT 4",)),
    Section("Side Events & Banquets", "🎪", "sheet", "#15A0AA",
            sheets=("side events, CBD, Ֆուրշետներ", "side events")),
    Section("State Orders (պետական պատվերներ)", "📜", "sheet", "#B0571A",
            sheets=("պետական պատվերներ", "պետական գնումներ")),
    Section("Compliments", "🎁", "compliments", "#C8553D"),
)
SECTION_BY_KEY = {s.key: s for s in SECTIONS}
SALES_SECTIONS = tuple(s for s in SECTIONS if s.kind == "sheet")

# Every sheet is parsed by shape, not by name:
#   * an iiko OLAP pivot (header row with Учетный день / Тип оплаты / Чеков / Сумма …) → daily rows;
#   * otherwise a period-summary sheet (Banquet Hall, Side Events, State Orders): one total in
#     column C / "Сумма со скидкой" / the Итого row, plus the period written on the sheet
#     ("01.10.2026 по 21.10.2026") → a period total that is never flagged as missing.

# Payment-type consolidation. Exact labels first (after casefold/strip), then prefixes.
PAYMENT_MAP: dict[str, str] = {
    "pos arcus": "Bank Cards",
    "банковские карты": "Bank Cards",
    "наличные": "Cash",
    "փոխանցում": "Bank Transfers / Invoices",
}
PAYMENT_PREFIXES: dict[str, str] = {
    "փոխանց": "Bank Transfers / Invoices",     # Փոխանցում / Փոխանցումով / Փոխանցում (invoice)
    "безнал": "Bank Transfers / Invoices",     # Безналичный расчёт
    "перечисл": "Bank Transfers / Invoices",
    "transfer": "Bank Transfers / Invoices",
    "invoice": "Bank Transfers / Invoices",
    "наличн": "Cash",
    "cash": "Cash",
    "банковск": "Bank Cards",
    "pos ": "Bank Cards",
    "card": "Bank Cards",
}
PAYMENT_ORDER = ("Bank Cards", "Cash", "Bank Transfers / Invoices")   # column order in the day table

# Payment-type label that marks free-of-charge / promotional orders in iiko.
COMPLIMENT_MARKERS = ("без оплаты",)

# ---------------------------------------------------------------- date presets
PRESET_FULL = "Full Event Period"
PRESET_TODAY = "Today"
PRESET_YESTERDAY = "Yesterday"
PRESET_WEEK = "This Week"
PRESET_CUSTOM = "Custom Date Range"
PRESETS = (PRESET_FULL, PRESET_TODAY, PRESET_YESTERDAY, PRESET_WEEK, PRESET_CUSTOM)

# ---------------------------------------------------------------- brand palette
# COP17 2026 Armenia accents: earth green, slate grey, gold — on an off-white console.
THEME = dict(
    green="#2E7D4F",
    green_dark="#1F5F3F",
    green_soft="#E6F1EA",
    blue="#4F6472",
    blue_soft="#EBEFF2",
    gold="#C98F0E",
    gold_soft="#FBF3E1",
    coral="#C8553D",
    bg="#F6F7F4",
    surface="#FFFFFF",
    border="#E1E6E0",
    ink="#15231B",
    ink_2="#4A5A50",
    ink_3="#7B897F",
    up="#1E8E5A",
    down="#C8553D",
)

# Categorical colours for sections in charts (fixed order — never cycled).
# Validated as colour-blind-safe and ≥3:1 on white in this order; keep the order if you edit.
CHART_COLORS = {sec.key: sec.color for sec in SECTIONS if sec.kind == "sheet"}
CHART_COLORS["Compliments"] = "#7A8780"
