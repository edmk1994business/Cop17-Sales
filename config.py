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
# Dropbox direct link (dl=1). Override with SOURCE_URL in .streamlit/secrets.toml.
DEFAULT_SOURCE_URL = (
    "https://www.dropbox.com/scl/fi/0qn6dhg9a166d13nt95ec/COP-17-Sales.xlsx"
    "?rlkey=owkahbr1fyaht9jb3z5qfjl0u&dl=1"
)
LOCAL_FALLBACK = "data/COP-17-Sales.xlsx"
CACHE_TTL_SECONDS = 300


# ---------------------------------------------------------------- sections
@dataclass(frozen=True)
class Section:
    key: str          # internal id and tab label (exact sheet name for live sheets)
    icon: str
    kind: str         # "global" | "sheet" | "sample" | "compliments"
    color: str        # accent used on the tab, the KPI rail and the charts
    sheet: str | None = None   # workbook sheet to load (kind == "sheet" / "sample")

    @property
    def label(self) -> str:
        return f"{self.icon} {self.key}"


SECTIONS: tuple[Section, ...] = (
    Section("General", "🌐", "global", "#2E7D4F"),
    Section("LOT 3", "🏪", "sheet", "#3C6E9E", sheet="LOT 3"),
    Section("LOT 8", "🏪", "sheet", "#3C6E9E", sheet="LOT 8"),
    Section("LOT 9", "🏪", "sheet", "#3C6E9E", sheet="LOT 9"),
    Section("LOT 10", "🏪", "sheet", "#3C6E9E", sheet="LOT 10"),
    Section("LOT 4", "🏪", "sample", "#3C6E9E", sheet="LOT 4"),
    Section("side events, CBD, Ֆուրշետներ", "🎪", "sample", "#C98F0E",
            sheet="side events, CBD, Ֆուրշետներ"),
    Section("պետական պատվերներ", "🏛️", "sample", "#1F5F3F", sheet="պետական պատվերներ"),
    Section("Compliments", "🎁", "compliments", "#C8553D"),
)
SECTION_BY_KEY = {s.key: s for s in SECTIONS}
SALES_SECTIONS = tuple(s for s in SECTIONS if s.kind in ("sheet", "sample"))

# Sheets listed as "sample" are generated ONLY when the workbook has no such sheet.
# The moment a real sheet with that name appears in the workbook, it is used instead.
SAMPLE_PROFILES: dict[str, dict] = {
    "LOT 4": dict(
        seed=4,
        checks=(70, 160),             # checks per trading day
        aov=(3_200, 5_800),           # average order value, ֏
        payments={"POS Arcus": 0.55, "Банковские карты": 0.30, "Наличные": 0.15},
        active_days=1.0,              # share of event days with sales
        discount_share=0.0,           # 0 → no "Сумма скидки" column at all
        compliments=(0, 3),           # free-of-charge checks per day (без оплаты)
    ),
    "side events, CBD, Ֆուրշետներ": dict(
        seed=7,
        checks=(2, 9),
        aov=(180_000, 650_000),
        payments={"Փոխանցումով": 0.65, "Банковские карты": 0.35},
        active_days=0.6,
        discount_share=0.0,
        compliments=(0, 1),
    ),
    "պետական պատվերներ": dict(
        seed=11,
        checks=(1, 4),
        aov=(450_000, 1_400_000),
        payments={"Փոխանցումով": 0.85, "Банковские карты": 0.15},
        active_days=0.45,
        discount_share=0.0,
        compliments=(0, 0),
    ),
}

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
# COP17 2026 Armenia accents: earth green, slate blue, gold — on an off-white console.
THEME = dict(
    green="#2E7D4F",
    green_dark="#1F5F3F",
    green_soft="#E6F1EA",
    blue="#3C6E9E",
    blue_soft="#E7EEF5",
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
CHART_COLORS = {
    "LOT 3": "#2E7D4F",
    "LOT 8": "#2F6BB5",
    "LOT 9": "#BC860C",
    "LOT 10": "#8A4FC7",
    "LOT 4": "#D04A3B",
    "side events, CBD, Ֆուրշետներ": "#15A0AA",
    "պետական պատվերներ": "#B0571A",
    "Compliments": "#7A8780",
}
